# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import argparse
import logging
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import messagebox

from logilocal.device import ROOT
from logilocal.system import single_instance


def main():
    parser=argparse.ArgumentParser(description='Logi Local — offline G703 control')
    parser.add_argument('--tray',action='store_true')
    parser.add_argument('--enable',action='store_true')
    parser.add_argument('--smoke-test',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    (ROOT/'local').mkdir(exist_ok=True)
    handler=RotatingFileHandler(ROOT/'local'/'logilocal.log',maxBytes=1_000_000,backupCount=3,encoding='utf-8')
    logging.basicConfig(level=logging.INFO,handlers=[handler],format='%(asctime)s %(levelname)s %(message)s')
    if args.smoke_test:
        import ctypes
        import json
        import hid
        from logilocal.gui import App
        from logilocal.wininput import INPUT
        from logilocal.config import load
        root=tk.Tk();root.withdraw();root.update()
        report={'tk':root.tk.call('info','patchlevel'),'input_size':ctypes.sizeof(INPUT),
                'profiles':len(load()['profiles']),'hid_interfaces':len(hid.enumerate(0x046D,0xC539)),
                'root':str(ROOT)}
        root.destroy()
        (ROOT/'local'/'smoke-test.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return
    mutex=single_instance()
    if not mutex:
        root=tk.Tk();root.withdraw()
        messagebox.showinfo('Logi Local','起動済みです。通知領域のマウスアイコンから設定を開いてください。')
        root.destroy();return
    from logilocal.gui import App
    root=tk.Tk()
    try:
        app=App(root,tray=args.tray,enable=args.enable)
        root.mainloop()
    except Exception:
        logging.exception('Application failed')
        raise


if __name__=='__main__':main()
