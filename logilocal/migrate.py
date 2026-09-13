# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
"""Read-only G HUB settings import; unsupported actions are reported explicitly."""
import copy
import json
import os
import sqlite3
import time

from .config import DEFAULT, HID_VK, validate
from .device import ROOT


def convert_macro(card):
    macro = card['macro']
    if macro['type'] != 'SEQUENCE': raise ValueError('非対応のマクロ種類')
    sequence = macro['sequence']
    # Import only explicit simple sequences; other modes cannot be inferred safely.
    if not sequence.get('useSimpleActions'):
        raise ValueError('複合シーケンスは手動での移行が必要です')
    steps = []
    for component in sequence.get('simpleSequence',{}).get('components',[]):
        if 'delay' in component:
            steps.append({'wait':component['delay']['durationMs']})
        elif 'keyboard' in component:
            k = component['keyboard']; hid = int(k['hidUsage'])
            if hid not in HID_VK: raise ValueError(f'非対応の HID キー {hid}')
            steps.append({'key':f'hid:{hid}','down':k.get('isDown',False)})
        elif 'mouse' in component and 'button' in component['mouse']:
            b = component['mouse']['button']
            steps.append({'mouse':int(b['hidUsage']),'down':b.get('isDown',False)})
        else: raise ValueError(f'非対応のマクロステップ: {list(component)}')
    return {'mode':'once','steps':steps}


def import_ghub():
    source = os.path.join(os.environ['LOCALAPPDATA'],'LGHUB','settings.db')
    backups = ROOT/'backups'; backups.mkdir(exist_ok=True)
    snapshot = backups/f'ghub-{time.time_ns()}.db'
    with sqlite3.connect('file:'+source+'?mode=ro',uri=True) as src:
        with sqlite3.connect(snapshot) as dest: src.backup(dest)
        row = src.execute('select file from data order by _id desc limit 1').fetchone()
    data = json.loads(row[0])
    cards = {c['id']:c for c in data['cards']['cards']}
    apps = {a['applicationId']:a for a in data['applications']['applications']}
    result = {'version':1,'profiles':[],'macros':{}}
    warnings = []
    for profile in data['profiles']['profiles']:
        if not any(a['slotId'].startswith('g703hero_') for a in profile.get('assignments',[])): continue
        app = apps[profile['applicationId']]
        p = copy.deepcopy(DEFAULT['profiles'][0])
        p['name'] = app.get('name','Profile')
        if p['name'] == 'APPLICATION_NAME_DESKTOP': p['name']='デスクトップ'
        p['apps'] = [app['applicationPath']] if app.get('applicationPath') else []
        for assignment in profile['assignments']:
            slot,cid = assignment['slotId'],assignment['cardId']
            card = cards.get(cid)
            if slot == 'g703hero_mouse_settings' and card:
                settings = card['mouseSettings']; dpi = settings['dpiTable']
                p.update(dpi=dpi['activeDpi'],dpi_levels=dpi['levels'],rate=settings['reportRate']['value'])
            if not slot.startswith('g703hero_g') or not slot.endswith('_m1'): continue
            button = slot[len('g703hero_g'):].split('_')[0]
            if button not in '123456': continue
            try:
                if card and card.get('attribute') == 'MACRO_PLAYBACK':
                    name = card['name']
                    result['macros'][name] = convert_macro(card)
                    p['buttons'][button] = 'macro:'+name
                elif cid.startswith('0f82f693-5b78-4cf5-867e-'):
                    raw = bytes.fromhex(cid.rsplit('-',1)[1])
                    category,usage = raw[0],raw[1]
                    if category == 1 and usage in HID_VK:
                        p['buttons'][button] = f'key:hid:{usage}'
                    elif category == 2 and usage in (1,2,3,4,5):
                        p['buttons'][button] = f'mouse:{usage}'
                    elif category == 4 and usage == 4:
                        p['buttons'][button] = 'dpi-cycle'
                    else: raise ValueError(f'未対応のプリセット {category:02x}/{usage:02x}')
                else: raise ValueError('未対応の割り当て')
            except (ValueError,KeyError) as e:
                warnings.append(f"{p['name']} G{button}: {e}。既定の割り当てを保持しました。")
        result['profiles'].append(p)
    if not result['profiles']: raise ValueError('G703 HERO の設定が見つかりません。')
    validate(result)
    return result,warnings,snapshot
