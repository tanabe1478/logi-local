# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import logging
import queue
import threading
import time
from pathlib import Path

from .config import load, match_profile
from .device import Mouse, ProtocolError
from .wininput import Output, foreground_exe

LOG = logging.getLogger(__name__)


class MacroPlayer:
    def __init__(self, output):
        self.output = output
        self.jobs = {}
        self.lock = threading.RLock()

    def trigger(self, button, macro, down):
        mode = macro.get('mode','once')
        with self.lock:
            active = self.jobs.get(button)
            if not down:
                if mode == 'hold' and active: active[0].set()
                return
            if active:
                if mode == 'toggle': active[0].set()
                return
            cancel = threading.Event()
            owner = object()

            def run():
                try:
                    while not cancel.is_set():
                        for step in macro['steps']:
                            if cancel.is_set(): break
                            if 'wait' in step:
                                if cancel.wait(step['wait']/1000): break
                            elif 'key' in step:
                                self.output.chord(owner,step['key'],step['down'])
                            else:
                                self.output.set(owner,'mouse',step['mouse'],step['down'])
                        self.output.release(owner)
                        if mode == 'once' or cancel.wait(.01): break
                except Exception:
                    LOG.exception('Macro failed')
                finally:
                    try: self.output.release(owner)
                    finally:
                        with self.lock:
                            self.jobs.pop(button,None)

            thread = threading.Thread(target=run,daemon=True,name='Macro')
            self.jobs[button] = (cancel,thread)
            thread.start()

    def stop(self):
        with self.lock:
            jobs = list(self.jobs.values())
            for cancel,_ in jobs: cancel.set()
        for _,thread in jobs: thread.join(2)


class Engine:
    """One HID owner thread. Configuration requests and input events share it."""
    def __init__(self):
        self.events = queue.SimpleQueue()
        self.commands = queue.SimpleQueue()
        self.stop_event = threading.Event()
        self.output = Output()
        self.macros = MacroPlayer(self.output)
        self.config = load()
        self.profile = None
        self.enabled = False
        self.mask = 0
        self.held = {}
        self.mouse = None
        self.thread = None
        self.forced_profile = None
        self.actual_dpi = None
        self.owns_device = False

    def start(self):
        self.thread = threading.Thread(target=self.run,daemon=True,name='G703 HID')
        self.thread.start()

    def submit(self, name, *args):
        self.commands.put((name,args))

    def release(self):
        self.macros.stop()
        self.output.release()
        self.held.clear()

    def on_packet(self, data):
        if len(data) < 6 or data[:4] != bytes([0x11,1,self.mouse.feature(0x8110),0]):
            return
        mask = int.from_bytes(data[4:6],'big')
        previous,self.mask = self.mask,mask
        for i in range(6):
            if bool(previous & (1<<i)) == bool(mask & (1<<i)): continue
            down = bool(mask & (1<<i))
            button = str(i+1)
            self.events.put(('button',(button,down)))
            if not self.enabled or self.profile is None: continue
            if down:
                action = self.profile['buttons'][button]
                self.held[button] = action
            else:
                action = self.held.pop(button,'none')
            if action.startswith('key:'):
                self.output.chord(button,action[4:],down)
            elif action.startswith('macro:'):
                self.macros.trigger(button,self.config['macros'][action[6:]],down)
            elif action == 'dpi-cycle' and down:
                # Defer HID commands until the current request/response finishes.
                self.commands.put(('cycle',()))

    def apply(self, profile):
        self.release()
        self.profile = None
        m = self.mouse
        self.owns_device = True
        m.set_mode(False)
        mapping = [int(profile['buttons'][str(i)][6:]) if profile['buttons'][str(i)].startswith('mouse:') else 0
                   for i in range(1,7)]
        m.mapping(mapping)
        m.set_dpi(profile['dpi'])
        m.set_rate(profile['rate'])
        m.call(0x8110,1)
        self.actual_dpi = profile['dpi']
        self.profile = profile
        self.events.put(('profile',profile['name']))

    def fallback(self):
        self.release()
        self.profile = None
        if self.mouse:
            # An onboard profile works even when this application is closed.
            self.mouse.mapping([1,2,3,4,5,0])
            self.mouse.set_mode(True)
            self.mouse.select_profile(1)
            self.mouse.call(0x8110,2)
            self.owns_device = False

    def command(self, name, args):
        if name == 'reload':
            new = load()
            self.release()
            self.config,self.profile = new,None
            return
        if name == 'force':
            self.forced_profile = args[0]
            self.profile = None
            return
        if name == 'enable':
            if args[0]:
                # G HUB can overwrite host mappings. Explicitly reject competing ownership.
                from .system import ghub_running
                if ghub_running():
                    raise ProtocolError('G HUB が起動中です。「G HUB を終了」してから有効にしてください。')
                self.enabled = True
                self.profile = None
            else:
                self.enabled = False
                self.fallback()
            self.events.put(('enabled',self.enabled))
            return
        if self.mouse is None:
            raise ProtocolError('マウスが接続されていません。')
        if name == 'cycle' and self.profile:
            levels = self.profile['dpi_levels']
            current = self.actual_dpi
            nxt = levels[(levels.index(current)+1)%len(levels)] if current in levels else levels[0]
            self.mouse.set_dpi(nxt)
            self.actual_dpi = nxt
            self.events.put(('dpi',nxt))
        elif name == 'status':
            self.events.put(('status',self.mouse.status()))
        elif name == 'backup':
            self.events.put(('message',f'バックアップ: {self.mouse.backup()}'))
        elif name == 'onboard':
            from .onboard import store_profile
            profile = args[0]
            was_enabled = self.enabled
            self.enabled = False
            self.release()
            try:
                path = store_profile(self.mouse,profile)
                self.events.put(('message',f'本体に保存し、読み戻しを確認しました。バックアップ: {path}'))
            finally:
                self.profile = None
                self.enabled = was_enabled
        elif name == 'restore':
            from .onboard import restore_profile
            if self.enabled:
                raise ValueError('自動切り替えを停止してから復元してください。')
            restore_profile(self.mouse,Path(args[0]))
            self.events.put(('message','本体プロファイル1を復元しました。'))

    def run(self):
        status_due = 0
        foreground_due = 0
        reconnect_due = 0
        try:
            while not self.stop_event.is_set():
                try:
                    while not self.commands.empty():
                        name,args = self.commands.get()
                        try: self.command(name,args)
                        except Exception as e:
                            LOG.exception('Command %s failed',name)
                            self.events.put(('error',str(e)))
                    now = time.monotonic()
                    if self.mouse is None:
                        if now < reconnect_due:
                            self.stop_event.wait(.1); continue
                        reconnect_due = now+3
                        self.mouse = Mouse()
                        self.mouse.feature(0x8110)
                        self.mouse.on_event = self.on_packet
                        self.profile = None
                        self.mask = 0
                        status_due = 0
                    if self.enabled and now >= foreground_due:
                        foreground_due = now+.2
                        selected = next((p for p in self.config['profiles'] if p['name']==self.forced_profile),None)
                        selected = selected or match_profile(self.config,foreground_exe())
                        if selected is not self.profile:
                            self.apply(selected)
                    if now >= status_due:
                        status_due = now+30
                        status = self.mouse.status()
                        self.events.put(('status',status))
                        if self.enabled and status['mode'] != 2:
                            self.apply(self.profile or match_profile(self.config,foreground_exe()))
                    packet = bytes(self.mouse.h.read(64,20))
                    if packet: self.on_packet(packet)
                except Exception as e:
                    LOG.exception('Device unavailable')
                    self.events.put(('error',str(e)))
                    self.release()
                    if self.mouse:
                        if self.owns_device:
                            try: self.fallback()
                            except Exception: LOG.exception('Device fallback failed')
                        try: self.mouse.close()
                        except Exception: pass
                    self.mouse = None
                    self.stop_event.wait(1)
        finally:
            try:
                if self.enabled: self.fallback()
                self.release()
            except Exception:
                LOG.exception('Cleanup failed')
            if self.mouse: self.mouse.close()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(5)
