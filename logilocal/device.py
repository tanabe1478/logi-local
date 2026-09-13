# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
# Contains adaptations of Solaar profile/battery handling.
# Copyright (C) 2012-2013 Daniel Pavel
# Copyright (C) 2014-2024 Solaar Contributors
# Upstream: GPL-2.0-or-later; adaptations distributed under GPL-3.0-or-later.
# See THIRD_PARTY_NOTICES.md for provenance and modification details.
"""HID++ 2 transport and conservative G703 onboard profile access.

Protocol references: Logitech cpg-docs, libratbag hidpp20.c and Solaar.
No Logitech executables, services, network or proprietary SDK required.
"""
import binascii
import json
import struct
import time
import sys
from pathlib import Path

import hid

ROOT = Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent


class ProtocolError(RuntimeError):
    pass


def crc(data):
    return binascii.crc_hqx(data, 0xFFFF)


def valid_sector(data):
    return len(data) in (255, 256) and crc(data[:-2]) == int.from_bytes(data[-2:], 'big')


class Mouse:
    def __init__(self):
        wired = [d for d in hid.enumerate(0x046D, 0xC090)
                 if d['usage_page'] == 0xFF00 and d['usage'] == 2]
        entries = wired or [d for d in hid.enumerate(0x046D, 0xC539)
                   if d['usage_page'] == 0xFF00 and d['usage'] == 2]
        if len(entries) != 1:
            raise ProtocolError('G703 HERO をケーブルまたは LIGHTSPEED レシーバーで1台接続してください。')
        self.info = entries[0]
        self.device_index = 0xFF if wired else 1
        self.h = hid.device()
        self.h.open_path(self.info['path'])
        self.features = {}
        self.on_event = None
        self.swid = 8
        try:
            reply = self.request(0, 1, b'\0\0\x5a')
            if reply[0] < 2 or reply[2] != 0x5A:
                raise ProtocolError('HID++ 2 の応答を確認できません。')
            self.version = f'{reply[0]}.{reply[1]}'
            if 'G703' not in self.name():
                raise ProtocolError('このレシーバーの接続先は G703 ではありません。')
        except Exception:
            self.close()
            raise

    def close(self):
        self.h.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def request(self, feature, function, data=b'', timeout=1.2):
        if len(data) > 16 or not 0 <= function <= 15:
            raise ValueError('Invalid HID++ request')
        self.swid = self.swid % 15 + 1
        address = (function << 4) | self.swid
        device_index = getattr(self, 'device_index', 1)
        packet = bytes([0x11, device_index, feature, address]) + data.ljust(16, b'\0')
        if self.h.write(packet) != 20:
            raise ProtocolError('USB 送信が完了しませんでした。')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = bytes(self.h.read(64, 50))
            if len(response) < 7 or response[0] not in (0x10, 0x11) or response[1] != device_index:
                continue
            if response[3] & 15 == 0:
                if self.on_event:
                    self.on_event(response)
                continue
            if response[2] == 0xFF and response[3:5] == bytes([feature, address]):
                raise ProtocolError(f'HID++ error {response[5]:02x} ({feature:02x}/{function:x})')
            if response[2] == 0x8F and response[3:5] == bytes([feature, address]):
                raise ProtocolError(f'HID++ 1 error {response[5]:02x}')
            if response[2:4] == bytes([feature, address]):
                return response[4:]
        raise ProtocolError('マウスの応答待ちがタイムアウトしました。マウスを動かして再試行してください。')

    def feature(self, fid):
        if fid not in self.features:
            self.features[fid] = self.request(0, 0, fid.to_bytes(2, 'big'))[0]
        if not self.features[fid]:
            raise ProtocolError(f'非対応の機能: {fid:04x}')
        return self.features[fid]

    def call(self, fid, fn=0, data=b''):
        return self.request(self.feature(fid), fn, data)

    def name(self):
        length = self.call(0x0005)[0]
        result = b''
        while len(result) < length:
            result += self.call(0x0005, 1, bytes([len(result)]))
        return result[:length].decode('utf-8', errors='replace')

    def describe(self):
        d = self.call(0x8100)
        return dict(memory=d[0], format=d[1], macro=d[2], profiles=d[3],
                    factory_profiles=d[4], buttons=d[5], sectors=d[6],
                    sector_size=int.from_bytes(d[7:9], 'big'), flags=d[9])

    def supported_dpis(self):
        values = struct.unpack('>7H', self.call(0x2201, 1, b'\0')[1:15])
        result = []
        i = 0
        while i < len(values) and values[i]:
            if i + 2 < len(values) and values[i + 1] & 0xE000 == 0xE000:
                step = values[i + 1] & 0x1FFF
                if not step or values[i + 2] < values[i]:
                    raise ProtocolError('Invalid DPI range')
                result.extend(range(values[i], values[i + 2] + 1, step))
                i += 3
            else:
                result.append(values[i]); i += 1
        return result

    def status(self):
        result = dict(name=self.name(), protocol=self.version, onboard=self.describe())
        result['mode'] = self.call(0x8100, 2)[0]
        result['profile'] = int.from_bytes(self.call(0x8100, 4)[:2], 'big')
        result['dpi_index'] = self.call(0x8100, 11)[0]
        d = self.call(0x2201, 2, b'\0')
        result['dpi'] = int.from_bytes(d[1:3], 'big')
        result['report_rate_ms'] = self.call(0x8060, 1)[0]
        for fid in (0x1000, 0x1004, 0x1001):
            try:
                d = self.call(fid)
                result['battery'] = {'feature': f'{fid:04x}', 'raw': d.hex()}
                if fid == 0x1000:
                    result['battery'].update(percent=d[0], status=d[2])
                elif fid == 0x1004:
                    d = self.call(fid, 1)
                    result['battery'].update(percent=d[0], status=d[2], raw=d.hex())
                else:
                    voltage = int.from_bytes(d[:2], 'big')
                    result['battery'].update(millivolts=voltage, percent=battery_percent(voltage),
                                             estimated=True, charging=bool(d[2] & 0x80))
                break
            except ProtocolError:
                continue
        return result

    def ensure_layout(self):
        d = self.describe()
        if d['memory'] != 1 or d['format'] not in (1, 2, 3, 4) or d['macro'] != 1 or d['sector_size'] not in (255, 256):
            raise ProtocolError(f'未対応のオンボード形式: {d}')
        return d

    def read_sector(self, sector):
        size = self.describe()['sector_size']
        data = b''
        while len(data) + 16 <= size:
            data += self.call(0x8100, 5, struct.pack('>HH', sector, len(data)))[:16]
        if len(data) < size:
            data += self.call(0x8100, 5, struct.pack('>HH', sector, size-16))[16-(size-len(data)):16]
        return data

    def directory(self):
        self.ensure_layout()
        raw = self.read_sector(0)
        if not valid_sector(raw):
            raise ProtocolError('オンボードディレクトリの CRC が不正です。書き込みを中止します。')
        result = []
        for offset in range(0, 252, 4):
            sector = int.from_bytes(raw[offset:offset+2], 'big')
            if sector == 0xFFFF:
                return raw, result
            if not 1 <= sector < self.describe()['sectors']:
                raise ProtocolError('Invalid profile sector')
            result.append((sector, raw[offset+2]))
        raise ProtocolError('Missing directory terminator')

    def backup(self):
        desc = self.ensure_layout()
        directory, entries = self.directory()
        sectors = {'0': directory.hex()}
        for sector in range(1, desc['sectors']):
            sectors[str(sector)] = self.read_sector(sector).hex()
        data = dict(status=self.status(), sectors=sectors, entries=entries)
        folder = ROOT / 'backups'
        folder.mkdir(exist_ok=True)
        path = folder / f'onboard-{time.time_ns()}.json'
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return path

    def set_mode(self, onboard):
        mode = 1 if onboard else 2
        self.call(0x8100, 1, bytes([mode]))
        if self.call(0x8100, 2)[0] != mode:
            raise ProtocolError('モード切り替えの検証に失敗しました。')

    def set_dpi(self, dpi):
        if dpi not in self.supported_dpis():
            raise ValueError('マウスが対応する DPI を指定してください。')
        self.call(0x2201, 3, b'\0' + dpi.to_bytes(2, 'big'))
        actual = int.from_bytes(self.call(0x2201, 2, b'\0')[1:3], 'big')
        if actual != dpi:
            raise ProtocolError(f'DPI 検証失敗: {actual} != {dpi}')

    def mapping(self, values=None):
        if values is not None:
            if len(values) != 6 or any(not 0 <= x <= 6 for x in values):
                raise ValueError('Invalid live mapping')
            self.call(0x8110, 4, bytes(values))
        result = list(self.call(0x8110, 3)[:6])
        if values is not None and list(values) != result:
            raise ProtocolError('ボタン割り当ての読み戻し検証に失敗しました。')
        return result

    def set_rate(self, hz):
        if hz not in (125, 250, 500, 1000):
            raise ValueError('Invalid polling rate')
        interval = 1000 // hz
        supported = self.call(0x8060)[0]
        if not supported & (1 << (interval-1)):
            raise ValueError('Unsupported polling rate')
        self.call(0x8060, 2, bytes([interval]))
        if self.call(0x8060, 1)[0] != interval:
            raise ProtocolError('ポーリングレートの検証に失敗しました。')

    def select_profile(self, sector):
        if sector not in [s for s, enabled in self.directory()[1] if enabled]:
            raise ValueError('有効なオンボードプロファイルを指定してください。')
        self.call(0x8100, 3, sector.to_bytes(2, 'big'))
        if int.from_bytes(self.call(0x8100, 4)[:2], 'big') != sector:
            raise ProtocolError('プロファイル切り替えの検証に失敗しました。')

    def write_profile(self, sector, original, updated):
        self.ensure_layout()
        _, entries = self.directory()
        if sector not in [s for s, _ in entries] or not valid_sector(original) or not valid_sector(updated):
            raise ProtocolError('Invalid profile write')
        if self.read_sector(sector) != original:
            raise ProtocolError('設定が別のアプリによって変更されました。再読み込みしてください。')
        if original == updated:
            return None
        backup = self.backup()
        self.call(0x8100, 6, struct.pack('>HHH', sector, 0, len(updated)))
        for offset in range(0, len(updated), 16):
            self.call(0x8100, 7, updated[offset:offset+16])
        self.call(0x8100, 8)
        if self.read_sector(sector) != updated:
            raise ProtocolError(f'書き込み後の検証に失敗しました。バックアップ: {backup}')
        return backup


def decode_profile(data):
    if not valid_sector(data):
        raise ProtocolError('プロファイル CRC 不一致')
    return dict(rate_ms=data[0], default_index=data[1], shift_index=data[2],
                dpis=list(struct.unpack('<5H', data[3:13])),
                name=data[160:208].decode('utf-16le', errors='replace').rstrip('\0\uffff'),
                buttons=[data[32+i*4:36+i*4].hex() for i in range(6)])


def patch_profile(original, dpi=None, rate_ms=None, buttons=None):
    if not valid_sector(original):
        raise ProtocolError('プロファイル CRC 不一致')
    data = bytearray(original)
    if dpi is not None:
        if not 100 <= dpi <= 25600:
            raise ValueError('DPI out of range')
        # Keep all five levels; change only the default level selected at power-on.
        index = data[1]
        if index >= 5:
            raise ProtocolError('Invalid default DPI index')
        struct.pack_into('<H', data, 3 + index * 2, dpi)
    if rate_ms is not None:
        if rate_ms not in (1, 2, 4, 8):
            raise ValueError('Invalid report interval')
        data[0] = rate_ms
    for index, binding in (buttons or {}).items():
        if not 0 <= index < 6 or len(binding) != 4:
            raise ValueError('Invalid button binding')
        data[32+index*4:36+index*4] = binding
    data[-2:] = crc(data[:-2]).to_bytes(2, 'big')
    return bytes(data)


def battery_percent(mv):
    # Empirical voltage curve documented by Solaar; percentage is an estimate.
    points = [(3500,0),(3579,2),(3646,5),(3671,10),(3717,20),(3751,30),
              (3778,40),(3811,50),(3859,60),(3922,70),(3989,80),(4067,90),(4186,100)]
    for (lo, p), (hi, q) in zip(points, points[1:]):
        if lo <= mv <= hi:
            return round(p + (q-p)*(mv-lo)/(hi-lo))
    return 0 if mv < points[0][0] else 100
