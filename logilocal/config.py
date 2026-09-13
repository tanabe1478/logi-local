# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import copy
import json
import os
import re
from pathlib import Path

from .device import ROOT

CONFIG = ROOT / 'local' / 'config.json'
DEFAULT = {'version': 1, 'profiles': [
    {'name': 'デスクトップ', 'apps': [], 'dpi': 1600, 'dpi_levels': [400,800,1600,3200],
     'rate': 1000, 'buttons': {'1': 'mouse:1','2': 'mouse:2','3': 'mouse:3',
                            '4': 'mouse:4','5': 'mouse:5','6': 'dpi-cycle'}}], 'macros': {}}

# USB HID keyboard usages -> Windows virtual keys. Keyboard layout translation
# is delegated to Windows; macro documents retain their USB usage identifiers.
HID_VK = {**{x: x-4+65 for x in range(4,30)},
          **{x: x-30+49 for x in range(30,39)}, 39:48,
          40:13,41:27,42:8,43:9,44:32,45:189,46:187,47:219,48:221,
          49:220,51:186,52:222,53:192,54:188,55:190,56:191,57:20,
          **{x: x-58+112 for x in range(58,70)},
          70:44,71:145,72:19,73:45,74:36,75:33,76:46,77:35,78:34,
          79:39,80:37,81:40,82:38,83:144,84:111,85:106,86:109,87:107,
          88:13, **{x:x-89+97 for x in range(89,98)},98:96,99:110,
          224:162,225:160,226:164,227:91,228:163,229:161,230:165,231:92}
NAMED_KEYS = {'ctrl':162,'shift':160,'alt':164,'win':91,'space':32,'tab':9,
              'enter':13,'esc':27,'backspace':8,'delete':46,'left':37,'right':39,
              'up':38,'down':40,'home':36,'end':35,'pageup':33,'pagedown':34,
              'volumeup':175,'volumedown':174,'mute':173,'playpause':179,
              'nexttrack':176,'prevtrack':177}
NAMED_KEYS.update({f'f{i}':111+i for i in range(1,25)})


def keys(value):
    result = []
    for part in value.lower().split('+'):
        if part in NAMED_KEYS:
            result.append(NAMED_KEYS[part])
        elif len(part) == 1 and part.isascii() and part.isalnum():
            result.append(ord(part.upper()))
        elif part.startswith('hid:') and int(part[4:]) in HID_VK:
            result.append(HID_VK[int(part[4:])])
        else:
            raise ValueError(f'不明なキー: {part}')
    return result


def validate(config):
    if config.get('version') != 1 or not config.get('profiles'):
        raise ValueError('version=1 と profiles が必要です。')
    names = set()
    defaults = 0
    for p in config['profiles']:
        if not isinstance(p['name'], str) or not p['name'] or p['name'] in names:
            raise ValueError('プロファイル名を重複させないでください。')
        names.add(p['name'])
        if not isinstance(p['apps'], list) or any(not isinstance(a,str) or not a.lower().endswith('.exe') for a in p['apps']):
            raise ValueError('apps は exe 名またはフルパスの配列です。')
        defaults += not p['apps']
        for dpi in [p['dpi']] + p['dpi_levels']:
            if type(dpi) is not int or not 100 <= dpi <= 25600 or dpi % 50:
                raise ValueError('DPI は 100〜25600、50刻みです。')
        if not 1 <= len(p['dpi_levels']) <= 5 or p['dpi'] not in p['dpi_levels']:
            raise ValueError('DPI levels は1〜5個で、現在の DPI を含めてください。')
        if p['rate'] not in (125,250,500,1000):
            raise ValueError('rate は 125 / 250 / 500 / 1000 です。')
        if set(p['buttons']) != set('123456'):
            raise ValueError('ボタン1〜6の割り当てが必要です。')
        for action in p['buttons'].values():
            if action in ('none','dpi-cycle'):
                continue
            if action.startswith('mouse:') and action[6:] in '12345' and len(action)==7:
                continue
            if action.startswith('key:'):
                keys(action[4:]); continue
            if action.startswith('macro:') and action[6:] in config.get('macros',{}):
                continue
            raise ValueError(f'不明な割り当て: {action}')
    if defaults != 1:
        raise ValueError('apps が空の既定プロファイルを1個指定してください。')
    for name, macro in config.get('macros',{}).items():
        if macro.get('mode','once') not in ('once','hold','toggle'):
            raise ValueError(f'{name}: mode は once / hold / toggle')
        steps = macro['steps']
        if not 1 <= len(steps) <= 1000:
            raise ValueError('マクロは1〜1000ステップです。')
        held = set()
        for step in steps:
            if set(step) == {'wait'}:
                if type(step['wait']) is not int or not 0 <= step['wait'] <= 60000:
                    raise ValueError('wait は0〜60000msです。')
                continue
            if set(step) != {'key','down'} and set(step) != {'mouse','down'}:
                raise ValueError('ステップは wait / key+down / mouse+down です。')
            if type(step['down']) is not bool:
                raise ValueError('down は true / false です。')
            if 'key' in step:
                keys(step['key'])
                token = ('key',step['key'])
            else:
                if step['mouse'] not in (1,2,3,4,5):
                    raise ValueError('mouse は1〜5です。')
                token = ('mouse',step['mouse'])
            if step['down']:
                if token in held: raise ValueError('キーの二重押下があります。')
                held.add(token)
            else:
                if token not in held: raise ValueError('押していないキーの解放があります。')
                held.remove(token)
        if held:
            raise ValueError('マクロの末尾で全キーを解放してください。')
    return config


def load():
    if not CONFIG.exists():
        save(copy.deepcopy(DEFAULT))
    return validate(json.loads(CONFIG.read_text(encoding='utf-8')))


def save(config):
    validate(config)
    CONFIG.parent.mkdir(exist_ok=True)
    temp = CONFIG.with_suffix('.tmp')
    temp.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,CONFIG)


def match_profile(config, executable):
    def normalize(value):
        return re.sub(r'\\+',lambda m:'\\',value.replace('/', '\\')).casefold()
    executable = normalize(executable)
    for p in config['profiles']:
        if any(executable == normalize(a) if '\\' in a or '/' in a
               else executable.rsplit('\\',1)[-1] == a.casefold() for a in p['apps']):
            return p
    return next(p for p in config['profiles'] if not p['apps'])
