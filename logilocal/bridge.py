# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
"""Private stdio JSONL bridge for Electron; no listening network port."""
import json
import sys
import threading

from .config import load, save, validate
from .runtime import Engine
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
                   'firmware-check','firmware-download','firmware-import','firmware-update'}
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
