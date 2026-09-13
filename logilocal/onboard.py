# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import json
import struct

from .config import HID_VK, keys
from .device import patch_profile, ProtocolError, crc, valid_sector


def binding(action):
    if action == 'none': return bytes.fromhex('8000ffff')
    if action == 'dpi-cycle': return bytes.fromhex('9005ff00')
    if action.startswith('mouse:'):
        return b'\x80\x01' + (1 << (int(action[6:])-1)).to_bytes(2,'big')
    if action.startswith('key:'):
        modifiers = 0
        usage = 0
        for vk in keys(action[4:]):
            hid = next((h for h,v in HID_VK.items() if v==vk),None)
            if hid is None: raise ValueError('このキーは本体保存に対応していません。')
            if 224 <= hid <= 231:
                modifiers |= 1 << (hid-224)
            elif usage:
                raise ValueError('本体には修飾キー + 1キーのみ保存できます。')
            else: usage = hid
        return bytes([0x80,2,modifiers,usage])
    raise ValueError('マクロはローカル常駐アプリで実行します。本体保存には通常のキー割り当てを選んでください。')


def store_profile(mouse, profile):
    mouse.ensure_layout()
    supported = mouse.supported_dpis()
    if any(d not in supported for d in profile['dpi_levels']):
        raise ValueError('Unsupported DPI')
    buttons = {i:binding(profile['buttons'][str(i+1)]) for i in range(6)}
    original = mouse.read_sector(1)
    updated = bytearray(patch_profile(original,rate_ms=1000//profile['rate'],buttons=buttons))
    levels = profile['dpi_levels']
    struct.pack_into('<5H',updated,3,*(levels+[0]*(5-len(levels))))
    updated[1] = levels.index(profile['dpi'])
    updated[2] = min(updated[2],len(levels)-1)
    updated[-2:] = crc(updated[:-2]).to_bytes(2,'big')
    path = mouse.write_profile(1,original,bytes(updated))
    mouse.set_mode(True)
    mouse.select_profile(1)
    mouse.call(0x8100,12,bytes([updated[1]]))
    return path or '変更なし（書き込み省略）'


def restore_profile(mouse, path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['status']['name'] != mouse.name() or data['status']['onboard'] != mouse.describe():
        raise ProtocolError('バックアップの機種・形式が一致しません。')
    updated = bytes.fromhex(data['sectors']['1'])
    if not valid_sector(updated): raise ProtocolError('バックアップ CRC 不一致')
    mouse.write_profile(1,mouse.read_sector(1),updated)
    mouse.set_mode(True)
    mouse.select_profile(1)
