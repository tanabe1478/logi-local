# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
"""Windows input output only; no global input hooks or keyboard recording."""
import ctypes as C
from ctypes import wintypes as W
import threading

from .config import keys

U = C.WinDLL('user32', use_last_error=True)
K = C.WinDLL('kernel32', use_last_error=True)
UP = C.c_size_t


class MOUSEINPUT(C.Structure):
    _fields_ = [('dx',W.LONG),('dy',W.LONG),('mouseData',W.DWORD),
                ('dwFlags',W.DWORD),('time',W.DWORD),('dwExtraInfo',UP)]


class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk',W.WORD),('wScan',W.WORD),('dwFlags',W.DWORD),
                ('time',W.DWORD),('dwExtraInfo',UP)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg',W.DWORD),('wParamL',W.WORD),('wParamH',W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [('mi',MOUSEINPUT),('ki',KEYBDINPUT),('hi',HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type',W.DWORD),('u',INPUTUNION)]


U.SendInput.argtypes = [W.UINT,C.POINTER(INPUT),C.c_int]
U.SendInput.restype = W.UINT
U.GetForegroundWindow.restype = W.HWND
U.GetWindowThreadProcessId.argtypes = [W.HWND,C.POINTER(W.DWORD)]
K.OpenProcess.argtypes = [W.DWORD,W.BOOL,W.DWORD]
K.OpenProcess.restype = W.HANDLE
K.QueryFullProcessImageNameW.argtypes = [W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
K.CloseHandle.argtypes = [W.HANDLE]
U.MapVirtualKeyW.argtypes = [W.UINT,W.UINT]


def foreground_exe():
    pid = W.DWORD()
    U.GetWindowThreadProcessId(U.GetForegroundWindow(),C.byref(pid))
    handle = K.OpenProcess(0x1000,False,pid.value)
    if not handle:
        return ''
    try:
        size = W.DWORD(32768)
        buffer = C.create_unicode_buffer(size.value)
        return buffer.value if K.QueryFullProcessImageNameW(handle,0,buffer,C.byref(size)) else ''
    finally:
        K.CloseHandle(handle)


def send(kind, code, down):
    event = INPUT()
    if kind == 'key':
        event.type = 1
        scan = U.MapVirtualKeyW(code,4)
        # Scan codes are accepted by more games than virtual-key messages.
        if scan:
            flags = 8 | (0 if down else 2) | (1 if scan & 0xFF00 else 0)
            event.ki = KEYBDINPUT(0,scan & 0xFF,flags,0,0x4C4F4749)
        else:
            event.ki = KEYBDINPUT(code,0,0 if down else 2,0,0x4C4F4749)
    else:
        event.type = 0
        flags = {1:(2,4),2:(8,16),3:(32,64),4:(128,256),5:(128,256)}[code][not down]
        event.mi = MOUSEINPUT(0,0,code-3 if code>=4 else 0,flags,0,0x4C4F4749)
    if U.SendInput(1,C.byref(event),C.sizeof(event)) != 1:
        raise OSError('入力の送信に失敗しました。対象アプリの権限を確認してください。')


class Output:
    """Reference-count held outputs so overlapping macros cannot release each other."""
    def __init__(self, sender=send):
        self.sender = sender
        self.owners = {}
        self.lock = threading.RLock()

    def set(self, owner, kind, code, down):
        token = (kind,code)
        with self.lock:
            owners = self.owners.setdefault(token,set())
            if down and owner not in owners:
                if not owners: self.sender(kind,code,True)
                owners.add(owner)
            elif not down and owner in owners:
                if len(owners)==1: self.sender(kind,code,False)
                owners.remove(owner)
            if not owners: self.owners.pop(token,None)

    def chord(self, owner, chord, down):
        codes = keys(chord)
        for code in codes if down else reversed(codes):
            self.set(owner,'key',code,down)

    def release(self, owner=None):
        with self.lock:
            for (kind,code), owners in list(self.owners.items()):
                for item in list(owners):
                    if owner is None or item == owner:
                        self.set(item,kind,code,False)
