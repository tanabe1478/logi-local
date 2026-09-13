# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
"""Private stdio JSONL bridge for Electron; no listening network port."""
import json
import sys
import threading

from .config import load, save, validate, match_profile
from .runtime import Engine, foreground_exe
from .system import single_instance, stop_ghub, autostart_enabled, set_autostart

OUTPUT_LOCK = threading.Lock()


def emit(value):
    with OUTPUT_LOCK:
        try:
            sys.stdout.write(json.dumps(value, ensure_ascii=False)+'\n')
            sys.stdout.flush()
        except (OSError, BrokenPipeError):
            pass


class BridgeEngine(Engine):
    def command(self, name, args):
        if name == 'barrier':
            args[0].set()
            return
        if name != 'rpc':
            return super().command(name, args)
        request = args[0]
        operation = request.get('op')
        try:
            result = self.dispatch(operation, request.get('args', []))
            emit({'id':request['id'], 'result':result})
        except Exception as error:
            emit({'id':request.get('id'), 'error':str(error)})

    def dispatch(self, operation, args):
        if operation == 'service-autostart-get':
            from .system import service_autostart_enabled
            return service_autostart_enabled()
        if operation == 'service-autostart-set':
            from .system import set_service_autostart, service_autostart_enabled
            if type(args[0]) is not bool: raise ValueError('自動起動は真偽値で指定してください。')
            set_service_autostart(args[0])
            return service_autostart_enabled()
        if operation == 'onboard-expected':
            profile=args[0]
            current=next((p for p in load()['profiles'] if p['name']==profile['name']),None)
            if current != profile: raise ValueError('確認中に設定が変わりました。本体には保存しません。')
            super().command('onboard',(profile,))
            return True
        if operation == 'firmware-status':
            from . import firmware
            if args and args[0]: firmware.refresh_catalog()
            if self.mouse is None: raise ValueError('本体が接続されていません。')
            info = firmware.inspect(self.mouse)
            info.pop('unit',None)
            self.events.put(('firmware-info',info))
            return info
        if operation == 'runtime-get':
            status = self.mouse.status() if self.mouse else None
            if status: self.events.put(('status',status))
            return {'enabled':self.enabled,'forced_profile':self.forced_profile,
                    'active_profile':self.profile['name'] if self.profile else None,'device':status}
        if operation == 'runtime-set':
            options = args[0]
            if set(options) - {'enabled','profile'}: raise ValueError('不明な常駐設定です。')
            if 'enabled' in options and type(options['enabled']) is not bool: raise ValueError('enabled は真偽値です。')
            name = options.get('profile',self.forced_profile)
            if name is not None and not any(p['name']==name for p in self.config['profiles']):
                raise ValueError('指定されたプロファイルがありません。')
            if options.get('enabled',self.enabled) and self.mouse is None:
                raise ValueError('本体が接続されていないため適用できません。')
            if 'enabled' in options: super().command('enable',(options['enabled'],))
            if 'profile' in options: super().command('force',(name,))
            verified = False
            if self.enabled:
                selected = next((p for p in self.config['profiles'] if p['name']==self.forced_profile),None)
                selected = selected or match_profile(self.config,foreground_exe())
                self.apply(selected)
                actual = self.mouse.status()
                if actual['dpi'] != selected['dpi'] or 1000//actual['report_rate_ms'] != selected['rate']:
                    raise ValueError('本体から読み戻した DPI・レートが設定値と一致しません。')
                verified = True
            return {**self.dispatch('runtime-get',()),'device_applied':verified}
        if operation == 'legacy-autostart-get': return autostart_enabled()
        if operation == 'legacy-autostart-disable':
            set_autostart(False)
            return True
        if operation == 'config-get': return load()
        if operation == 'config-validate': return validate(args[0])
        if operation == 'config-save':
            save(args[0])
            super().command('reload', ())
            return load()
        if operation == 'config-save-expected':
            if load() != args[1]:
                raise ValueError('提案後に設定が変わりました。変更案を作り直してください。')
            save(args[0])
            super().command('reload', ())
            return load()
        if operation == 'ghub-stop':
            stop_ghub()
            return True
        if operation == 'ghub-import':
            from .migrate import import_ghub
            config, warnings, backup = import_ghub()
            # Preview in the renderer; saving is a separate user action.
            return {'config':config, 'warnings':warnings}
        allowed = {'enable','force','status','backup','onboard','restore',
                   'firmware-check','firmware-refresh','firmware-reconcile','firmware-download','firmware-import','firmware-update'}
        if operation not in allowed:
            raise ValueError('未対応の操作です。')
        if operation == 'firmware-update':
            self.firmware_busy = True
            emit({'event':'firmware-busy','value':True})
        try:
            super().command(operation, args)
        finally:
            if operation == 'firmware-update':
                self.firmware_busy = False
                emit({'event':'firmware-busy','value':False})
        return True


def main():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    mutex = single_instance()
    if not mutex:
        emit({'event':'fatal','value':'Logi Local が起動済みです。旧画面を終了してから開いてください。'})
        return
    engine = BridgeEngine()
    engine.start()
    finished = threading.Event()

    def events():
        while not finished.is_set():
            while not engine.events.empty():
                kind, value = engine.events.get()
                # Do not send private unit identifiers into the web renderer.
                if kind == 'firmware-info':
                    value = {k:v for k,v in value.items() if k != 'unit'}
                emit({'event':kind,'value':value})
            finished.wait(.025)

    pump = threading.Thread(target=events, daemon=True)
    pump.start()
    emit({'event':'ready','value':True})
    try:
        for line in sys.stdin:
            request = {}
            try:
                if len(line) > 2_000_000: raise ValueError('リクエストが大きすぎます。')
                request = json.loads(line)
                if not isinstance(request,dict) or not isinstance(request.get('id'),str):
                    raise ValueError('リクエスト形式が不正です。')
                if engine.firmware_busy:
                    raise ValueError('ファームウェア更新中です。完了までお待ちください。')
                if request.get('op') == 'shutdown':
                    # Queue a barrier so a previously queued firmware command
                    # cannot begin after stop has already decided it is idle.
                    barrier = threading.Event()
                    engine.commands.put(('barrier',(barrier,)))
                    barrier.wait()
                    if engine.firmware_busy: raise ValueError('ファームウェア更新中です。')
                    engine.stop()
                    emit({'id':request['id'],'result':True})
                    break
                engine.commands.put(('rpc',(request,)))
            except Exception as error:
                emit({'id':request.get('id') if isinstance(request,dict) else None,'error':str(error)})
    finally:
        barrier = threading.Event()
        if not engine.stop_event.is_set():
            engine.commands.put(('barrier',(barrier,)))
            barrier.wait()
        engine.stop()
        finished.set()
        pump.join(1)


if __name__ == '__main__':
    main()
