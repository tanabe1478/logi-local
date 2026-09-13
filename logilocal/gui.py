# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import copy
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from .config import load, save, validate, DEFAULT, HID_VK, NAMED_KEYS
from .device import ROOT
from .runtime import Engine
from .system import set_autostart, autostart_enabled, stop_ghub

BG = '#101820'
PANEL = '#192630'
INK = '#e9f2f7'
MUTED = '#9db3c2'
ACCENT = '#60dbc2'
BUTTONS = ['左クリック','右クリック','ホイールクリック','サイド後方','サイド前方','DPI ボタン']
ACTION_LABELS = {'そのまま':'native','キー / ショートカット':'key','マクロ':'macro',
                 'DPI を順に切り替え':'dpi-cycle','無効':'none',
                 '左クリック':'mouse:1','右クリック':'mouse:2','中央クリック':'mouse:3',
                 '戻る':'mouse:4','進む':'mouse:5'}


def readable_key(value):
    if not value.startswith('hid:'): return value
    try: vk = HID_VK[int(value[4:])]
    except (KeyError,ValueError): return value
    if 65 <= vk <= 90 or 48 <= vk <= 57: return chr(vk)
    return next((k for k,v in NAMED_KEYS.items() if v==vk),value)


class App:
    def __init__(self, root, tray=False, enable=False):
        self.root = root
        self.config = load()
        self.selected = 0
        self.loading = False
        self.icon = None
        self.ui_events = queue.SimpleQueue()
        self.engine = Engine()
        self.root.title('Logi Local — G703')
        self.root.geometry('1080x780')
        self.root.minsize(920,690)
        self.root.configure(bg=BG)
        self.root.protocol('WM_DELETE_WINDOW',self.hide)
        self.style()
        self.build()
        self.load_profile(0)
        self.engine.start()
        self.start_tray()
        self.root.after(80,self.poll)
        if enable: self.engine.submit('enable',True)
        if tray: self.root.after(300,self.hide)

    def style(self):
        s = ttk.Style(self.root)
        s.theme_use('clam')
        s.configure('.',background=BG,foreground=INK,font=('Yu Gothic UI',10),borderwidth=0)
        s.configure('TFrame',background=BG)
        s.configure('Card.TFrame',background=PANEL)
        s.configure('TLabel',background=BG)
        s.configure('Muted.TLabel',foreground=MUTED)
        s.configure('Title.TLabel',font=('Yu Gothic UI',24,'bold'))
        s.configure('Hero.TLabel',font=('Yu Gothic UI',16,'bold'),foreground=ACCENT)
        s.configure('TButton',background='#29404c',foreground=INK,padding=(14,9))
        s.map('TButton',background=[('active','#385462'),('disabled','#202d34')])
        s.configure('Accent.TButton',background='#176955',foreground='white')
        s.map('Accent.TButton',background=[('active','#22816a')])
        s.configure('TEntry',fieldbackground='#253743',foreground=INK,padding=6)
        s.configure('TCombobox',fieldbackground='#253743',background='#253743',foreground=INK,padding=5)
        s.map('TCombobox',fieldbackground=[('readonly','#253743')],foreground=[('readonly',INK)])
        s.configure('TNotebook',background=BG)
        s.configure('TNotebook.Tab',background=PANEL,padding=(22,12))
        s.map('TNotebook.Tab',background=[('selected','#29434c')],foreground=[('selected',ACCENT)])
        s.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=INK,rowheight=30)
        s.configure('Treeview.Heading',background='#29404c',foreground=INK,padding=8)
        s.map('Treeview',background=[('selected','#24594f')])
        s.configure('TCheckbutton',background=BG,foreground=INK)
        self.root.option_add('*TCombobox*Listbox.background','#253743')
        self.root.option_add('*TCombobox*Listbox.foreground',INK)

    def build(self):
        outer = ttk.Frame(self.root,padding=24); outer.pack(fill='both',expand=True)
        head = ttk.Frame(outer); head.pack(fill='x')
        ttk.Label(head,text='Logi Local',style='Title.TLabel').pack(side='left')
        ttk.Label(head,text='G703 LIGHTSPEED  /  ローカル接続',style='Muted.TLabel').pack(side='left',padx=20)
        ttk.Button(head,text='通知領域へ',command=self.hide).pack(side='right')
        stats = ttk.Frame(outer,padding=(0,16)); stats.pack(fill='x')
        self.status_text = tk.StringVar(value='G703 に接続中…')
        ttk.Label(stats,textvariable=self.status_text,style='Hero.TLabel').pack(side='left')
        ttk.Button(stats,text='更新',command=lambda:self.engine.submit('status')).pack(side='right')
        bar = ttk.Frame(outer); bar.pack(fill='x',pady=(0,16))
        self.enabled = tk.BooleanVar()
        ttk.Checkbutton(bar,text='アプリ別設定・マクロを有効にする',variable=self.enabled,
                        command=lambda:self.engine.submit('enable',self.enabled.get())).pack(side='left')
        self.active = tk.StringVar(value='常駐処理: 停止中')
        ttk.Label(bar,textvariable=self.active,style='Muted.TLabel').pack(side='right')
        self.tabs = ttk.Notebook(outer); self.tabs.pack(fill='both',expand=True)
        self.profile_tab = ttk.Frame(self.tabs,padding=18)
        self.macro_tab = ttk.Frame(self.tabs,padding=18)
        self.device_tab = ttk.Frame(self.tabs,padding=18)
        self.firmware_tab = ttk.Frame(self.tabs,padding=18)
        self.tabs.add(self.profile_tab,text='プロファイルとボタン')
        self.tabs.add(self.macro_tab,text='マクロ')
        self.tabs.add(self.device_tab,text='本体保存と設定')
        self.tabs.add(self.firmware_tab,text='ファームウェア')
        self.build_profiles(); self.build_macros(); self.build_device()
        self.build_firmware()
        foot = ttk.Frame(outer); foot.pack(fill='x',pady=(16,0))
        self.notice = tk.StringVar(value='設定はこの PC に保存されます。アカウント・インターネット接続は不要です。')
        ttk.Label(foot,textvariable=self.notice,style='Muted.TLabel',wraplength=760).pack(side='left')
        ttk.Button(foot,text='保存して反映',style='Accent.TButton',command=self.save_all).pack(side='right')

    def build_firmware(self):
        frame = self.firmware_tab
        self.firmware_info = None
        self.firmware_text = tk.StringVar(value='「本体を確認」で接続方式と現在のバージョンを読み取ります。')
        ttk.Label(frame,text='G703 HERO 純正ファームウェア',style='Hero.TLabel').pack(anchor='w',pady=(0,14))
        ttk.Label(frame,textvariable=self.firmware_text,wraplength=840).pack(anchor='w',pady=10)
        ttk.Label(frame,text='公式公開カタログの G703 HERO 更新候補  ·  G HUB 不要\n'
                  '公式候補の確認後、取得済みファイルはオフラインで使えます。\n'
                  '転送と障害時の復旧は G703 実機では未検証です。更新が必要な旧版の本体だけが対象です。',
                  wraplength=840,style='Muted.TLabel').pack(anchor='w',pady=12)
        row = ttk.Frame(frame); row.pack(fill='x',pady=10)
        self.firmware_controls = []
        for index,(label,command) in enumerate([('本体を確認',lambda:self.firmware_command('firmware-check')),
                              ('純正ファイルを取得',lambda:self.firmware_command('firmware-download')),
                              ('取得済み depot を選ぶ',self.firmware_import),
                              ('公式の更新候補を確認',lambda:self.firmware_command('firmware-refresh')),
                              ('更新結果を再確認',lambda:self.firmware_command('firmware-reconcile'))]):
            button = ttk.Button(row,text=label,command=command)
            button.grid(row=index//3,column=index%3,padx=(0,8),pady=4); self.firmware_controls.append(button)
        self.firmware_update_button = ttk.Button(frame,text='更新内容を確認して実行',
                                                command=self.firmware_update,state='disabled')
        self.firmware_update_button.pack(anchor='w',pady=14)
        self.firmware_progress = ttk.Progressbar(frame,maximum=100)
        self.firmware_progress.pack(fill='x',pady=12)
        self.firmware_stage = tk.StringVar(value='未確認')
        ttk.Label(frame,textvariable=self.firmware_stage,wraplength=840).pack(anchor='w')

    def firmware_command(self, name, *args):
        self.firmware_info = None
        self.firmware_update_button.configure(state='disabled')
        for button in self.firmware_controls: button.configure(state='disabled')
        self.firmware_stage.set('処理中…')
        self.engine.submit(name,*args)

    def firmware_import(self):
        path = filedialog.askopenfilename(parent=self.root,filetypes=[('Logitech depot','*.depot')])
        if path: self.firmware_command('firmware-import',path)

    def firmware_update(self):
        info = self.firmware_info
        if not info or not info['eligible']: return
        if messagebox.askyesno('純正ファームウェアの更新',
                f'G703 HERO: {info["version"]} → {info["candidate"]}\n\n'
                'G HUB を終了し、本体の USB ケーブルを接続したままにしてください。\n'
                '開始後は完了まで PC の電源・スリープ・ケーブルを操作しないでください。\n\n'
                'この転送処理は実機未検証です。失敗時の自動復旧は未対応で、'
                '純正ツールによる復旧が必要になる可能性があります。\n'
                '本体設定のバックアップはファームウェアの復元用ではありません。\n\n'
                'この内容で更新を開始しますか？',parent=self.root):
            self.firmware_command('firmware-update')

    def build_profiles(self):
        frame = self.profile_tab
        row = ttk.Frame(frame); row.pack(fill='x',pady=(0,12))
        self.profile_choice = ttk.Combobox(row,state='readonly',width=27)
        self.profile_choice.pack(side='left')
        self.profile_choice.bind('<<ComboboxSelected>>',self.switch_profile)
        ttk.Button(row,text='追加',command=self.add_profile).pack(side='left',padx=6)
        ttk.Button(row,text='複製',command=self.copy_profile).pack(side='left')
        ttk.Button(row,text='削除',command=self.delete_profile).pack(side='left',padx=6)
        ttk.Button(row,text='この設定に固定',command=self.force_profile).pack(side='right')
        ttk.Button(row,text='自動切り替え',command=lambda:self.engine.submit('force',None)).pack(side='right',padx=6)
        fields = ttk.Frame(frame); fields.pack(fill='x')
        fields.columnconfigure(1,weight=1)
        self.profile_name = tk.StringVar(); self.apps = tk.StringVar()
        self.dpi = tk.StringVar(); self.levels = tk.StringVar(); self.rate = tk.StringVar()
        for r,label,var in [(0,'名前',self.profile_name),(1,'対象アプリ',self.apps),(2,'DPI',self.dpi),
                            (3,'DPI 切り替え候補',self.levels)]:
            ttk.Label(fields,text=label).grid(row=r,column=0,sticky='w',padx=(0,16),pady=5)
            entry = ttk.Entry(fields,textvariable=var)
            entry.grid(row=r,column=1,sticky='ew',pady=5)
        ttk.Button(fields,text='exe を選択',command=self.browse_exe).grid(row=1,column=2,padx=(10,0))
        ttk.Label(fields,text='空欄 = 既定。複数は ; で区切る',style='Muted.TLabel').grid(row=0,column=2,padx=10)
        ttk.Label(fields,text='100〜25600 / 50刻み',style='Muted.TLabel').grid(row=2,column=2,padx=10)
        ttk.Label(fields,text='例: 400, 800, 1600, 3200',style='Muted.TLabel').grid(row=3,column=2,padx=10)
        ttk.Label(fields,text='ポーリングレート').grid(row=4,column=0,sticky='w',pady=5)
        ttk.Combobox(fields,textvariable=self.rate,values=['125','250','500','1000'],state='readonly',width=12).grid(row=4,column=1,sticky='w',pady=5)
        ttk.Label(fields,text='Hz',style='Muted.TLabel').grid(row=4,column=2,sticky='w')
        rows = ttk.Frame(frame); rows.pack(fill='x',pady=(14,0))
        rows.columnconfigure(2,weight=1)
        self.action_vars = []; self.value_vars = []; self.value_widgets=[]
        for i,label in enumerate(BUTTONS):
            ttk.Label(rows,text=f'G{i+1}   {label}',width=23).grid(row=i,column=0,sticky='w',pady=3)
            typ = tk.StringVar(); val = tk.StringVar()
            self.action_vars.append(typ); self.value_vars.append(val)
            combo = ttk.Combobox(rows,textvariable=typ,values=list(ACTION_LABELS),state='readonly',width=24)
            combo.grid(row=i,column=1,padx=(0,12),pady=3)
            value = ttk.Combobox(rows,textvariable=val,values=[])
            value.grid(row=i,column=2,sticky='ew',pady=3)
            self.value_widgets.append(value)
            combo.bind('<<ComboboxSelected>>',lambda e,i=i:self.action_changed(i))

    def action_changed(self,i):
        kind = ACTION_LABELS[self.action_vars[i].get()]
        widget = self.value_widgets[i]
        if kind=='macro':
            widget.configure(state='readonly',values=list(self.config['macros']))
            if self.value_vars[i].get() not in self.config['macros']:
                self.value_vars[i].set(next(iter(self.config['macros']),''))
        elif kind=='key':
            widget.configure(state='normal',values=['ctrl','shift','alt','F','space','ctrl+c','ctrl+v','ctrl+shift+tab','volumeup','volumedown','mute','playpause'])
        else:
            widget.configure(state='disabled')
            self.value_vars[i].set('')

    def read_profile(self):
        p = copy.deepcopy(self.config['profiles'][self.selected])
        p.update(name=self.profile_name.get().strip(),apps=[s.strip() for s in self.apps.get().split(';') if s.strip()],
                 dpi=int(self.dpi.get()),dpi_levels=[int(s.strip()) for s in self.levels.get().split(',')],rate=int(self.rate.get()))
        for i in range(6):
            kind = ACTION_LABELS[self.action_vars[i].get()]
            if kind=='native': action = f'mouse:{i+1}' if i<5 else 'dpi-cycle'
            elif kind in ('key','macro'): action = kind+':'+self.value_vars[i].get().strip()
            else: action = kind
            p['buttons'][str(i+1)] = action
        test = copy.deepcopy(self.config); test['profiles'][self.selected]=p
        validate(test)
        self.config = test
        return p

    def load_profile(self,index):
        self.selected=index
        p=self.config['profiles'][index]
        self.profile_choice.configure(values=[x['name'] for x in self.config['profiles']]); self.profile_choice.current(index)
        self.profile_name.set(p['name']); self.apps.set('; '.join(p['apps']))
        self.dpi.set(str(p['dpi'])); self.levels.set(', '.join(map(str,p['dpi_levels']))); self.rate.set(str(p['rate']))
        for i in range(6):
            action=p['buttons'][str(i+1)]
            if action.startswith('key:'): kind='key'; value=readable_key(action[4:])
            elif action.startswith('macro:'): kind='macro'; value=action[6:]
            else: kind=action; value=''
            if action==f'mouse:{i+1}': kind='native'
            self.action_vars[i].set(next(k for k,v in ACTION_LABELS.items() if v==kind))
            self.value_vars[i].set(value); self.action_changed(i)

    def switch_profile(self,event=None):
        index=self.profile_choice.current()
        try: self.read_profile(); self.load_profile(index)
        except Exception as e:
            self.profile_choice.current(self.selected); self.error(e)

    def add_profile(self):
        try: self.read_profile()
        except Exception as e: return self.error(e)
        path=filedialog.askopenfilename(parent=self.root,title='対象アプリを選択',filetypes=[('実行ファイル','*.exe')])
        if not path: return
        p=copy.deepcopy(DEFAULT['profiles'][0]); p.update(name=os.path.basename(path),apps=[path])
        names=[x['name'] for x in self.config['profiles']]
        while p['name'] in names: p['name']+=' 新規'
        self.config['profiles'].append(p); self.load_profile(len(self.config['profiles'])-1)

    def copy_profile(self):
        try: p=copy.deepcopy(self.read_profile())
        except Exception as e: return self.error(e)
        path=filedialog.askopenfilename(parent=self.root,title='複製先の対象アプリ',filetypes=[('実行ファイル','*.exe')])
        if not path:return
        p['name']+=' コピー'; p['apps']=[path]
        while p['name'] in [x['name'] for x in self.config['profiles']]:p['name']+=' コピー'
        self.config['profiles'].append(p); self.load_profile(len(self.config['profiles'])-1)

    def delete_profile(self):
        if not self.config['profiles'][self.selected]['apps']:
            return self.error('既定プロファイルは削除できません。')
        del self.config['profiles'][self.selected]; self.load_profile(0)

    def browse_exe(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('実行ファイル','*.exe')])
        if path:self.apps.set(path)

    def force_profile(self):
        if self.save_all():self.engine.submit('force',self.config['profiles'][self.selected]['name'])

    def build_macros(self):
        f=self.macro_tab
        row=ttk.Frame(f);row.pack(fill='x',pady=(0,12))
        self.macro_choice=ttk.Combobox(row,state='readonly',width=32,values=list(self.config['macros']))
        self.macro_choice.pack(side='left');self.macro_choice.bind('<<ComboboxSelected>>',lambda e:self.refresh_steps())
        ttk.Button(row,text='新規マクロ',command=self.new_macro).pack(side='left',padx=8)
        ttk.Button(row,text='削除',command=self.delete_macro).pack(side='left')
        self.macro_mode=tk.StringVar(value='once')
        ttk.Label(row,text='再生').pack(side='left',padx=(20,8))
        modes=ttk.Combobox(row,textvariable=self.macro_mode,state='readonly',values=['once','hold','toggle'],width=10)
        modes.pack(side='left');modes.bind('<<ComboboxSelected>>',self.change_macro_mode)
        ttk.Label(f,text='once: 1回   /   hold: 押している間繰り返す   /   toggle: 押すたびに開始・停止',style='Muted.TLabel').pack(anchor='w',pady=(0,10))
        self.steps=ttk.Treeview(f,columns=('num','type','value'),show='headings',height=10,selectmode='browse')
        for c,title,width in [('num','#',50),('type','動作',180),('value','キー / 待機時間',450)]:
            self.steps.heading(c,text=title);self.steps.column(c,width=width,stretch=c=='value')
        self.steps.pack(fill='both',expand=True)
        self.steps.bind('<<TreeviewSelect>>',self.select_step)
        editor=ttk.Frame(f);editor.pack(fill='x',pady=(14,0))
        self.step_kind=tk.StringVar(value='キー押下');self.step_value=tk.StringVar(value='space')
        ttk.Combobox(editor,textvariable=self.step_kind,values=['キー押下','キー解放','待機 ms','マウス押下','マウス解放'],state='readonly',width=16).pack(side='left')
        ttk.Entry(editor,textvariable=self.step_value,width=22).pack(side='left',padx=8)
        ttk.Button(editor,text='追加',command=self.add_step).pack(side='left')
        ttk.Button(editor,text='選択行を更新',command=self.update_step).pack(side='left',padx=6)
        ttk.Button(editor,text='削除',command=self.remove_step).pack(side='left')
        ttk.Button(editor,text='↑',command=lambda:self.move_step(-1)).pack(side='left',padx=6)
        ttk.Button(editor,text='↓',command=lambda:self.move_step(1)).pack(side='left')
        ttk.Label(f,text='キー例: space / X / ctrl+c。押下と解放を対にします。マウスは1〜5。保存時に整合性を検証します。',
                  style='Muted.TLabel',wraplength=870).pack(anchor='w',pady=(12,0))
        if self.config['macros']:self.macro_choice.current(0);self.refresh_steps()

    def macro(self):
        return self.config['macros'].get(self.macro_choice.get())

    def refresh_steps(self):
        for i in self.steps.get_children():self.steps.delete(i)
        m=self.macro()
        if not m:return
        self.macro_mode.set(m.get('mode','once'))
        for i,step in enumerate(m['steps']):
            if 'wait' in step: kind,value='待機 ms',str(step['wait'])
            elif 'key' in step:kind,value=('キー押下' if step['down'] else 'キー解放'),readable_key(step['key'])
            else:kind,value=('マウス押下' if step['down'] else 'マウス解放'),str(step['mouse'])
            self.steps.insert('','end',iid=str(i),values=(i+1,kind,value))

    def new_macro(self):
        name=simpledialog.askstring('新規マクロ','マクロ名',parent=self.root)
        if not name:return
        if name in self.config['macros']:return self.error('同名のマクロがあります。')
        self.config['macros'][name]={'mode':'once','steps':[{'key':'space','down':True},{'wait':50},{'key':'space','down':False}]}
        self.macro_choice.configure(values=list(self.config['macros']));self.macro_choice.set(name);self.refresh_steps()

    def delete_macro(self):
        name=self.macro_choice.get()
        if any('macro:'+name in p['buttons'].values() for p in self.config['profiles']):
            return self.error('ボタンに割り当て済みです。先に割り当てを変更してください。')
        self.config['macros'].pop(name,None);self.macro_choice.configure(values=list(self.config['macros']))
        self.macro_choice.set(next(iter(self.config['macros']),''));self.refresh_steps()

    def change_macro_mode(self,event=None):
        if self.macro():self.macro()['mode']=self.macro_mode.get()

    def parsed_step(self):
        kind=self.step_kind.get();value=self.step_value.get().strip()
        if kind=='待機 ms':return {'wait':int(value)}
        if kind.startswith('マウス'):return {'mouse':int(value),'down':kind.endswith('押下')}
        return {'key':value,'down':kind.endswith('押下')}

    def select_step(self,event=None):
        selected=self.steps.selection()
        if selected:
            _,kind,value=self.steps.item(selected[0],'values');self.step_kind.set(kind);self.step_value.set(value)

    def add_step(self):
        if not self.macro():return
        try:self.macro()['steps'].append(self.parsed_step());self.refresh_steps()
        except Exception as e:self.error(e)

    def update_step(self):
        if not self.steps.selection():return
        try:self.macro()['steps'][int(self.steps.selection()[0])]=self.parsed_step();self.refresh_steps()
        except Exception as e:self.error(e)

    def remove_step(self):
        if self.steps.selection():del self.macro()['steps'][int(self.steps.selection()[0])];self.refresh_steps()

    def move_step(self,delta):
        if not self.steps.selection():return
        i=int(self.steps.selection()[0]);j=i+delta;steps=self.macro()['steps']
        if 0<=j<len(steps):steps[i],steps[j]=steps[j],steps[i];self.refresh_steps();self.steps.selection_set(str(j))

    def build_device(self):
        f=self.device_tab
        ttk.Label(f,text='常駐なしでも使える、本体への保存',style='Hero.TLabel').pack(anchor='w')
        ttk.Label(f,text='選択中のプロファイルを本体スロット1に保存します。DPI・ポーリングレート・通常のボタン割り当てが対象です。\nアプリ別の自動切り替えとマクロは、このローカルアプリが起動している間に使えます。',
                  style='Muted.TLabel',wraplength=860).pack(anchor='w',pady=12)
        row=ttk.Frame(f);row.pack(fill='x',pady=8)
        ttk.Button(row,text='選択中の設定を本体に保存',command=self.write_onboard,style='Accent.TButton').pack(side='left')
        ttk.Button(row,text='本体をバックアップ',command=lambda:self.engine.submit('backup')).pack(side='left',padx=10)
        ttk.Button(row,text='本体スロット1を復元',command=self.restore).pack(side='left')
        ttk.Separator(f).pack(fill='x',pady=22)
        ttk.Label(f,text='移行と起動',style='Hero.TLabel').pack(anchor='w')
        row=ttk.Frame(f);row.pack(fill='x',pady=14)
        ttk.Button(row,text='G HUB の設定を取り込む',command=self.import_ghub).pack(side='left')
        ttk.Button(row,text='G HUB を終了',command=self.stop_ghub).pack(side='left',padx=10)
        ttk.Button(row,text='設定をエクスポート',command=self.export).pack(side='left')
        ttk.Button(row,text='設定をインポート',command=self.import_config).pack(side='left',padx=10)
        self.autostart=tk.BooleanVar(value=autostart_enabled())
        ttk.Checkbutton(f,text='Windows 起動時に通知領域で起動する',variable=self.autostart,command=self.autostart_changed).pack(anchor='w',pady=6)
        ttk.Button(f,text='保存先フォルダを開く',command=lambda:os.startfile(str(ROOT/'local'))).pack(anchor='w',pady=12)
        ttk.Label(f,text='G HUB と同時に有効化すると設定が競合するため、起動中は有効化を停止します。\nバッテリー残量は本体の電圧からの推定値です。USB レシーバー接続の G703 HERO で検証しています。\nマクロの精密なタイミングやゲーム側での入力受付は、Windows と対象アプリにも依存します。',
                  style='Muted.TLabel',wraplength=860).pack(anchor='w',pady=10)
        ttk.Button(f,text='アプリを完全に終了',command=self.quit).pack(anchor='w',pady=8)

    def write_onboard(self):
        try:
            p=self.read_profile()
            from .onboard import binding
            for action in p['buttons'].values():binding(action)
            self.engine.submit('onboard',copy.deepcopy(p));self.notice.set('本体をバックアップして保存しています…')
        except Exception as e:self.error(e)

    def restore(self):
        path=filedialog.askopenfilename(parent=self.root,initialdir=ROOT/'backups',filetypes=[('本体バックアップ','onboard-*.json')])
        if path:self.engine.submit('restore',path)

    def import_ghub(self):
        try:
            from .migrate import import_ghub
            config,warnings,backup=import_ghub()
            save(config);self.config=config;self.load_profile(0)
            self.macro_choice.configure(values=list(config['macros']));self.macro_choice.set(next(iter(config['macros']),''));self.refresh_steps()
            self.engine.submit('reload');self.notice.set(f'{len(config["profiles"])} プロファイルを取り込みました。')
            if warnings:messagebox.showwarning('移行が必要な設定','\n'.join(warnings),parent=self.root)
        except Exception as e:self.error(e)

    def stop_ghub(self):
        try:stop_ghub();self.notice.set('G HUB を終了しました。ローカル制御を有効にできます。')
        except Exception as e:self.error(e)

    def export(self):
        if not self.save_all():return
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.json',filetypes=[('設定','*.json')])
        if path:
            from pathlib import Path
            Path(path).write_text(json.dumps(self.config,ensure_ascii=False,indent=2),encoding='utf-8')

    def import_config(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('設定','*.json')])
        if not path:return
        try:
            from pathlib import Path
            config=validate(json.loads(Path(path).read_text(encoding='utf-8')))
            save(config);self.config=config;self.load_profile(0)
            self.macro_choice.configure(values=list(config['macros']));self.macro_choice.set(next(iter(config['macros']),''));self.refresh_steps()
            self.engine.submit('reload')
        except Exception as e:self.error(e)

    def autostart_changed(self):
        try:set_autostart(self.autostart.get())
        except Exception as e:self.error(e)

    def save_all(self):
        try:
            self.read_profile();save(self.config);self.engine.submit('reload')
            self.profile_choice.configure(values=[x['name'] for x in self.config['profiles']])
            self.notice.set('設定を保存しました。ローカル制御が有効な場合はすぐに反映されます。')
            return True
        except Exception as e:self.error(e);return False

    def error(self,e):
        messagebox.showerror('Logi Local',str(e),parent=self.root)

    def poll(self):
        while not self.ui_events.empty():
            action=self.ui_events.get()
            if action=='show':self.show()
            elif action=='quit':self.quit();return
            elif action=='toggle':self.engine.submit('enable',not self.engine.enabled)
        while not self.engine.events.empty():
            kind,value=self.engine.events.get()
            if kind=='status':
                b=value.get('battery',{});pct=b.get('percent','?')
                text=f'{value["dpi"]:,} DPI    ·    {1000//value["report_rate_ms"]} Hz    ·    電池 約 {pct}%'
                if b.get('charging'):text+='  充電中'
                self.status_text.set(text)
                if self.icon:self.icon.title=f'G703 · {pct}% · {value["dpi"]} DPI'
            elif kind=='profile':self.active.set(f'適用中: {value}')
            elif kind=='dpi':self.notice.set(f'DPI を {value} に切り替えました。')
            elif kind=='enabled':
                self.enabled.set(value)
                if not value:self.active.set('常駐処理: 停止中 / 本体設定を使用')
            elif kind=='error':
                self.notice.set(value);self.enabled.set(self.engine.enabled)
            elif kind=='message':self.notice.set(value)
            elif kind=='firmware-info':
                self.firmware_info = value
                connection = 'USB ケーブル' if value['wired'] else 'LIGHTSPEED（更新時はケーブルが必要）'
                cached = '取得・検証済み' if value['cached'] else '未取得'
                self.firmware_text.set(f'本体: {value["version"]}  /  接続: {connection}\n'
                                       f'対応済み候補: {value["candidate"]}  /  ファイル: {cached}')
                self.firmware_stage.set(value['reason'])
            elif kind=='firmware-progress':
                self.firmware_stage.set(value[0]);self.firmware_progress['value']=value[1]
            elif kind=='firmware-error':
                self.firmware_stage.set(value)
            elif kind=='firmware-idle':
                for button in self.firmware_controls:button.configure(state='normal')
                eligible = self.firmware_info and self.firmware_info['eligible']
                self.firmware_update_button.configure(state='normal' if eligible else 'disabled')
        self.root.after(80,self.poll)

    def start_tray(self):
        import pystray
        from PIL import Image,ImageDraw
        image=Image.new('RGBA',(64,64),BG);draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((17,6,47,57),14,fill=ACCENT)
        draw.line((32,7,32,25),fill=BG,width=3)
        draw.rounded_rectangle((29,16,35,28),3,fill=BG)
        self.icon=pystray.Icon('LogiLocal',image,'Logi Local — G703',menu=pystray.Menu(
            pystray.MenuItem('設定を開く',lambda:self.ui_events.put('show'),default=True),
            pystray.MenuItem('ローカル制御を切り替え',lambda:self.ui_events.put('toggle')),
            pystray.MenuItem('終了',lambda:self.ui_events.put('quit'))))
        threading.Thread(target=self.icon.run,daemon=True,name='Tray').start()

    def hide(self):
        if self.icon:self.root.withdraw()

    def show(self):
        self.root.deiconify();self.root.lift();self.root.focus_force()

    def quit(self):
        if self.engine.firmware_busy:
            self.show()
            self.notice.set('ファームウェア更新中です。完了まで終了できません。')
            return
        self.engine.stop()
        if self.icon:self.icon.stop()
        self.root.destroy()
