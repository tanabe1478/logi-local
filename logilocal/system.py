# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import ctypes as C
from ctypes import wintypes as W
import subprocess
import sys
import winreg
from .device import ROOT

K = C.WinDLL('kernel32',use_last_error=True)


class PROCESSENTRY32(C.Structure):
    _fields_ = [('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),
                ('th32DefaultHeapID',C.c_size_t),('th32ModuleID',W.DWORD),
                ('cntThreads',W.DWORD),('th32ParentProcessID',W.DWORD),
                ('pcPriClassBase',W.LONG),('dwFlags',W.DWORD),('szExeFile',W.WCHAR*260)]


K.CreateToolhelp32Snapshot.argtypes = [W.DWORD,W.DWORD]
K.CreateToolhelp32Snapshot.restype = W.HANDLE
K.Process32FirstW.argtypes = [W.HANDLE,C.POINTER(PROCESSENTRY32)]
K.Process32NextW.argtypes = [W.HANDLE,C.POINTER(PROCESSENTRY32)]
K.CloseHandle.argtypes = [W.HANDLE]
K.CreateMutexW.argtypes = [C.c_void_p,W.BOOL,W.LPCWSTR]
K.CreateMutexW.restype = W.HANDLE


def ghub_running():
    snapshot = K.CreateToolhelp32Snapshot(2,0)
    if snapshot == C.c_void_p(-1).value: raise OSError('Cannot enumerate processes')
    entry = PROCESSENTRY32(); entry.dwSize = C.sizeof(entry)
    names = []
    try:
        ok = K.Process32FirstW(snapshot,C.byref(entry))
        while ok:
            if entry.szExeFile.lower() in ('lghub.exe','lghub_agent.exe','lghub_system_tray.exe'):
                names.append(entry.szExeFile)
            ok = K.Process32NextW(snapshot,C.byref(entry))
    finally: K.CloseHandle(snapshot)
    return names


def stop_ghub():
    for exe in set(ghub_running()):
        subprocess.run(['taskkill','/IM',exe,'/F'],creationflags=subprocess.CREATE_NO_WINDOW,
                       capture_output=True,timeout=10)
    if ghub_running(): raise RuntimeError('G HUB を終了できませんでした。')


def set_autostart(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            if (ROOT/'LogiLocal.exe').exists():
                command = f'"{ROOT / "LogiLocal.exe"}" --tray --enable'
            else:
                exe = str(ROOT/'.venv'/'Scripts'/'pythonw.exe')
                command = f'"{exe}" "{ROOT / "launch.py"}" --tray --enable'
            winreg.SetValueEx(key,'LogiLocal',0,winreg.REG_SZ,command)
        else:
            try: winreg.DeleteValue(key,'LogiLocal')
            except FileNotFoundError: pass


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            return bool(winreg.QueryValueEx(key,'LogiLocal')[0])
    except FileNotFoundError: return False


def single_instance():
    handle = K.CreateMutexW(None,False,'Local\\LogiLocal-G703')
    if not handle: raise OSError('Cannot create mutex')
    if C.get_last_error() == 183:
        K.CloseHandle(handle)
        return None
    return handle
