# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent HID owner with authenticated local Windows pipe clients.

Only JSON bytes cross the pipe; multiprocessing pickle deserialization is not used.
GUI disconnection never changes device ownership or interrupts queued work.
"""
import hashlib
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client, Listener
from multiprocessing import AuthenticationError
from pathlib import Path

from .device import ROOT


def endpoint():
    directory = Path(os.environ['LOCALAPPDATA']) / 'LogiLocal'
    directory.mkdir(parents=True, exist_ok=True)
    keyfile = directory / 'pipe.key'
    try:
        descriptor = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(secrets.token_bytes(32))
    for _ in range(50):
        key = keyfile.read_bytes()
        if len(key) == 32:
            identity = hashlib.sha256(str(directory).lower().encode()).hexdigest()[:20]
            return rf'\\.\pipe\LogiLocal-{identity}', key
        time.sleep(.02)
    raise RuntimeError('制御プロセスの認証キーを読み込めません。')


def connect(start=True):
    address, key = endpoint()
    try:
        return Client(address, family='AF_PIPE', authkey=key)
    except OSError:
        if not start: raise
    subprocess.Popen([str(ROOT/'.venv/Scripts/pythonw.exe'), '-m', 'logilocal.service', '--enable'],
                     cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
                     close_fds=True)
    for _ in range(100):
        try:
            return Client(address, family='AF_PIPE', authkey=key)
        except OSError:
            time.sleep(.1)
    raise RuntimeError('制御プロセスを起動できません。旧版のLogi Localをトレイから終了してください。')


class Service:
    def __init__(self, engine):
        self.engine = engine
        self.clients = {}
        self.recent = {}
        self.lock = threading.Lock()
        self.stopping = threading.Event()

    def publish(self, message):
        with self.lock:
            if message.get('event') in ('status','enabled','profile','firmware-info','firmware-busy'):
                self.recent[message['event']] = message
            for outgoing in list(self.clients.values()):
                try: outgoing.put_nowait(message)
                except queue.Full: pass

    def attach(self, connection):
        outgoing = queue.Queue(512)
        close_lock = threading.Lock()
        def close():
            with close_lock: connection.close()
        prefix = secrets.token_hex(16) + ':'
        with self.lock:
            self.clients[prefix] = outgoing
            for event in self.recent.values(): outgoing.put(event)
            outgoing.put({'event':'ready','value':True})

        def send():
            try:
                while True:
                    message = outgoing.get()
                    if message is None: break
                    if 'id' in message:
                        if not message['id'].startswith(prefix): continue
                        message = {**message, 'id':message['id'][len(prefix):]}
                    connection.send_bytes(json.dumps(message,ensure_ascii=False).encode('utf-8'))
            except (OSError, EOFError): pass
            finally: close()

        sender = threading.Thread(target=send, daemon=True)
        sender.start()
        try:
            while not self.stopping.is_set():
                request = json.loads(connection.recv_bytes(2_000_000))
                if not isinstance(request,dict) or not isinstance(request.get('id'),str):
                    raise ValueError('不正なリクエストです。')
                request['id'] = prefix + request['id']
                if request.get('op') == 'shutdown':
                    # A GUI closing only detaches. Stopping is owned by the tray.
                    self.publish({'id':request['id'],'result':True})
                    continue
                self.engine.commands.put(('rpc',(request,)))
        except (OSError, EOFError, ValueError): pass
        finally:
            with self.lock: self.clients.pop(prefix,None)
            try: outgoing.put_nowait(None)
            except queue.Full: pass
            close()

    def stop(self):
        # Barrier includes already queued writes before releasing HID ownership.
        if self.engine.firmware_busy: return False
        barrier = threading.Event()
        self.engine.commands.put(('barrier',(barrier,)))
        barrier.wait()
        if self.engine.firmware_busy: return False
        self.engine.stop()
        self.stopping.set()
        return True


def relay():
    from .bridge import emit
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    try: connection = connect()
    except Exception as error:
        emit({'event':'fatal','value':str(error)})
        return
    def receive():
        try:
            while True: emit(json.loads(connection.recv_bytes(2_000_000)))
        except (OSError,EOFError):
            emit({'event':'fatal','value':'マウス制御プロセスとの接続が終了しました。'})
    threading.Thread(target=receive,daemon=True).start()
    try:
        for line in sys.stdin:
            if len(line) > 2_000_000: raise ValueError('リクエストが大きすぎます。')
            connection.send_bytes(line.encode('utf-8'))
    finally: connection.close()


def main():
    from . import bridge
    from .system import single_instance
    mutex = single_instance()
    if not mutex: return
    engine = bridge.BridgeEngine()
    service = Service(engine)
    bridge.emit = service.publish
    address,key = endpoint()
    listener = Listener(address,family='AF_PIPE',authkey=key)
    engine.start()
    if '--enable' in sys.argv: engine.submit('enable',True)
    def accept():
        while not service.stopping.is_set():
            try: connection = listener.accept()
            except (OSError,EOFError,AuthenticationError): continue
            threading.Thread(target=service.attach,args=(connection,),daemon=True).start()
    def events():
        while not service.stopping.is_set():
            while not engine.events.empty():
                kind,value = engine.events.get()
                if kind == 'firmware-info': value={k:v for k,v in value.items() if k!='unit'}
                service.publish({'event':kind,'value':value})
            service.stopping.wait(.025)
    threading.Thread(target=accept,daemon=True).start()
    threading.Thread(target=events,daemon=True).start()
    import pystray
    from PIL import Image,ImageDraw
    image=Image.new('RGBA',(64,64),'#101418')
    ImageDraw.Draw(image).rounded_rectangle((17,6,47,57),14,fill='#86e2c7')
    def show():
        subprocess.Popen(['wscript.exe',str(ROOT/'Start-LogiLocal.vbs')],cwd=ROOT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    def stop(icon):
        if service.stop(): icon.stop()
        else: icon.notify('ファームウェア更新の完了までお待ちください。','終了できません')
    icon=pystray.Icon('LogiLocal',image,'Logi Local — マウス制御',menu=pystray.Menu(
        pystray.MenuItem('設定を開く',show,default=True),
        pystray.MenuItem('ローカル制御',lambda:engine.submit('enable',not engine.enabled),
                         checked=lambda item:engine.enabled),
        pystray.MenuItem('マウス制御を終了',stop)))
    try: icon.run()
    finally:
        if not service.stopping.is_set(): service.stop()
        listener.close()


if __name__ == '__main__':
    if '--relay' in sys.argv: relay()
    else: main()
