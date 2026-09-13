# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
# DFU sequencing adapted from fwupd, Copyright 2017 Richard Hughes,
# originally LGPL-2.1-or-later. See THIRD_PARTY_NOTICES.md.
"""Conservative, experimental G703 HERO signed firmware updater.

Only catalog-validated official images (or the pinned fallback) are accepted.
No vendor firmware is redistributed.
Bootloader identity and actual post-reboot version must be readable to proceed.
"""
import hashlib
import json
import os
import struct
import time
import urllib.request
from pathlib import Path

import hid

from .device import Mouse, ProtocolError, ROOT
from . import firmware_catalog as catalog

VERSION = '22.02.15'
URL = 'https://updates.ghub.logitechg.com/depots/58c73bea-abb7-4081-bf3a-9f4fd831ad09/g703_hero_dfu.depot'
DEPOT_HASH = 'e6ba148ca26a38232dc9570da053fe3df13453fdac9b7db864dc63c79ebc5b82'
IMAGE_HASH = '16acefe9a081632d5f9a1dc69fa777eb145ea31bf085091e5ae8ca7668fc8d05'
DEPOT_SIZE = 86404
CACHE = ROOT / 'local' / 'firmware'


def current_candidate():
    path = CACHE / 'catalog.json'
    if path.exists():
        candidate = json.loads(path.read_text(encoding='utf-8'))
        if candidate.get('source') != catalog.DETAILS_URL:
            raise ValueError('保存済み公式カタログの配布元が不正です。')
        # Reuse the URL/hash/size allowlist when loading persisted metadata.
        catalog.select_depot({'appId':'ghub13','platform':'win','channel':'public',
                              'buildId':candidate['build_id'], 'depots':[{
                                  'name':'g703_hero_dfu','url':candidate['url'].removeprefix(catalog.ORIGIN),
                                  'size':candidate['size'],'mac':candidate['sha256']}]})
        version_tuple(candidate['version'])
        return candidate
    return {'version':VERSION, 'url':URL, 'size':DEPOT_SIZE, 'sha256':DEPOT_HASH,
            'image_sha256':IMAGE_HASH, 'source':'bundled', 'checked_at':None}


def package_path(candidate):
    if candidate['source'] == 'bundled': return CACHE / 'g703_hero.depot'
    return CACHE / (candidate['sha256'] + '.depot')


def refresh_catalog():
    return catalog.refresh(CACHE, unpack_depot)


def unpack_depot(data):
    """Parse in memory: never interpret archive names as filesystem paths."""
    if len(data) < 8 or len(data) > 2_000_000 or data[:4] != b'\x10\x01\x17\x20':
        raise ValueError('純正 depot の形式が不正です。')
    size = struct.unpack_from('<I', data, 4)[0]
    if not 0 < size <= min(65536, len(data)-8):
        raise ValueError('depot メタデータ長が不正です。')
    entries = json.loads(data[8:8+size])['files']
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError('depot ファイル一覧が不正です。')
    offset, result = 8+size, {}
    for entry in entries:
        name = entry['name']
        if not isinstance(name, str) or name in result:
            raise ValueError('depot ファイル名が重複または不正です。')
        if offset+4 > len(data):
            raise ValueError('depot が途中で切れています。')
        length = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        if length > len(data)-offset:
            raise ValueError('depot ファイル長が不正です。')
        result[name] = data[offset:offset+length]
        offset += length
    if offset != len(data):
        raise ValueError('depot に予期しない末尾データがあります。')
    return result


def validate_package(data, candidate=None):
    if candidate and candidate['source'] != 'bundled':
        return catalog.parse_package(data, candidate, unpack_depot)[0]
    if len(data) != DEPOT_SIZE or hashlib.sha256(data).hexdigest() != DEPOT_HASH:
        raise ValueError('対応済みの純正パッケージと SHA-256 が一致しません。')
    files = unpack_depot(data)
    image = files['g703_hero_v22_02_15.dfu']
    meta = json.loads(files['dfu.json'])['contents']
    if len(meta) != 1 or meta[0]['version'] != VERSION:
        raise ValueError('更新メタデータが一致しません。')
    if (len(image) != 78688 or len(image) % 16 or
            hashlib.sha256(image).hexdigest() != IMAGE_HASH or
            image[:10] != b'\x01\x01MPM22_D0'):
        raise ValueError('署名付き純正イメージが一致しません。')
    return image


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('更新配布元のリダイレクトは未対応です。')


def obtain_package(local_path=None):
    candidate = current_candidate()
    if local_path:
        with open(local_path, 'rb') as stream:
            data = stream.read(candidate['size']+1)
    else:
        data = catalog.download(candidate['url'], candidate['size'])
    validate_package(data, candidate)
    CACHE.mkdir(parents=True, exist_ok=True)
    temporary = CACHE / 'package.tmp'
    temporary.write_bytes(data)
    temporary.replace(package_path(candidate))
    return package_path(candidate)


def version_tuple(value):
    parts = value.split('.')
    if len(parts) != 3 or any(not p.isdecimal() for p in parts):
        raise ValueError('バージョン形式が不正です。')
    return tuple(int(p) for p in parts)


def identity(mouse):
    raw = mouse.call(0x0003)
    if len(raw) < 13 or not 1 <= raw[0] <= 16:
        raise ProtocolError('本体の識別情報を読み取れません。')
    result = {'unit': raw[1:5].hex(), 'model': raw[7:13].hex(),
              'wired': mouse.info['product_id'] == 0xC090}
    for entity in range(raw[0]):
        info = mouse.call(0x0003, 1, bytes([entity]))
        if len(info) < 9:
            raise ProtocolError('ファームウェア情報が短すぎます。')
        if info[0] == 0 and info[1:4] == b'MPM' and info[8] & 1:
            parts = [info[4:5].hex(), info[5:6].hex(), info[6:8].hex()]
            if any(not p.isdecimal() for p in parts):
                raise ProtocolError('未知のファームウェアバージョン形式です。')
            result.update(version=f'{parts[0]}.{parts[1]}.{int(parts[2]):02d}', entity=entity)
    return result


def inspect(mouse):
    candidate = current_candidate()
    info = identity(mouse)
    if 'version' not in info or not info['model'].startswith('4086c090'):
        raise ProtocolError('対応する G703 HERO の本体情報を確認できません。')
    newer = version_tuple(candidate['version']) > version_tuple(info['version'])
    cached = False
    path = package_path(candidate)
    if path.exists():
        validate_package(path.read_bytes(), candidate)
        cached = True
    journal = CACHE / 'update-journal.json'
    journal_data = json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else {}
    journal_state = journal_data.get('state')
    verified = (journal_state == 'complete' and journal_data.get('unit') == info['unit'] and
                journal_data.get('sha256') == candidate['image_sha256'] and
                version_tuple(journal_data.get('target_version','0.0.0')) == version_tuple(info['version']))
    blockers = []
    if not newer: blockers.append('本体は公式候補と同じ版、または新しい版です。書き込みは不要です。')
    if not info['wired']: blockers.append('更新には本体のUSBケーブル接続が必要です。')
    if not cached: blockers.append('公式ファイルを取得・検証してください。')
    if journal_state not in (None,'complete','aborted-before-transfer'):
        blockers.append('未完了の更新記録があります。「更新結果を再確認」で本体の状態を照合してください。')
    return {**info, 'candidate': candidate['version'], 'cached': cached,
            'catalog_checked_at':candidate.get('checked_at'), 'catalog_source':candidate['source'],
            'journal_state':journal_state, 'hardware_write_verified':verified,
            'eligible': not blockers, 'blockers':blockers,
            'reason': ' '.join(blockers) if blockers else '公式候補への更新が可能です（転送は実機未検証）。'}


def reconcile_journal(mouse):
    """Read-only device check; never enter DFU, retry packets or erase memory."""
    path = CACHE / 'update-journal.json'
    if not path.exists(): return '未完了の更新記録はありません。'
    journal = json.loads(path.read_text(encoding='utf-8'))
    if journal.get('state') in ('complete','aborted-before-transfer'):
        return '更新記録に未完了の処理はありません。'
    actual = identity(mouse)
    if not actual['wired'] or actual['unit'] != journal.get('unit'):
        raise ProtocolError('更新記録と同じ本体をUSBケーブルで接続してください。')
    if version_tuple(actual.get('version','0.0.0')) == version_tuple(journal.get('target_version','0.0.1')):
        journal['state'] = 'complete'
        result = '同じ本体が更新先のバージョンで起動していることを確認しました。'
    elif (journal.get('failed_at') == 'entering-dfu' and
          version_tuple(actual.get('version','0.0.0')) == version_tuple(journal['version'])):
        journal['state'] = 'aborted-before-transfer'
        result = '転送開始前の失敗で、本体が元のバージョンで起動していることを確認しました。'
    else:
        raise ProtocolError('更新完了を確認できません。再書き込みは行わず、記録を保持します。')
    journal['reconciled_at'] = time.time()
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(journal,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)
    return result


class DfuTransport:
    """Exclusive boot transport; status events must not be consumed by Mouse."""
    def __init__(self, handle, feature):
        self.h, self.feature = handle, feature
        self.swid = 8

    def send(self, function, payload):
        self.swid = self.swid % 15 + 1
        address = function << 4 | self.swid
        frame = bytes([0x11, 0xff, self.feature, address]) + payload.ljust(16, b'\0')
        if len(frame) != 20 or self.h.write(frame) != 20:
            raise ProtocolError('DFU の USB 送信が完了しませんでした。再送は行いません。')
        return address

    def packet(self, function, payload):
        address = self.send(function, payload)
        deadline = time.monotonic()+150
        counter = None
        while time.monotonic() < deadline:
            data = bytes(self.h.read(64, 100))
            if len(data) < 7 or data[0] not in (0x10, 0x11) or data[1] != 0xff:
                continue
            if data[2] in (0xff, 0x8f) and data[3:5] == bytes([self.feature, address]):
                raise ProtocolError(f'DFU HID++ error: {data[5]:02x}')
            if len(data) < 9 or data[0] != 0x11 or data[2] != self.feature:
                continue
            # Only accept the exact reply, then asynchronous completion events.
            if data[3] != address and not (counter is not None and data[3] & 15 == 0):
                continue
            received = int.from_bytes(data[4:8], 'big')
            if counter is not None and received != counter:
                raise ProtocolError('DFU 完了通知のカウンターが一致しません。')
            counter = received
            status = data[8] & 0x7f
            if status in (1, 2, 5, 6):
                return status
            if status not in (3, 0x19, 0x23):
                raise ProtocolError(f'DFU が失敗しました（status 0x{status:02x}）。再送は行いません。')
        raise ProtocolError('DFU 応答がタイムアウトしました。再送は行いません。')


def transfer(transport, image, progress):
    if not image or len(image) % 16:
        raise ValueError('DFU は16バイト単位で転送する必要があります。')
    function = 4
    for offset in range(0, len(image), 16):
        transport.packet(function, image[offset:offset+16])
        function = (function+1) % 4
        if offset % 1024 == 0 or offset+16 == len(image):
            progress('転送中', (offset+16)*100/len(image))


def open_boot():
    entries = [d for d in hid.enumerate(0x046d, 0xaaf6)
               if d['usage_page'] == 0xff00 and d['usage'] == 2]
    if len(entries) != 1:
        raise ProtocolError('G703 HERO のブートローダーを1台だけ接続してください。')
    mouse = Mouse.__new__(Mouse)
    mouse.info, mouse.device_index = entries[0], 0xff
    mouse.features, mouse.on_event, mouse.swid = {}, None, 8
    mouse.h = hid.device()
    try:
        mouse.h.open_path(entries[0]['path'])
        mouse.feature(0x00d0)
        return mouse
    except Exception:
        mouse.close()
        raise


def wait_device(factory, timeout=30):
    deadline = time.monotonic()+timeout
    last = None
    while time.monotonic() < deadline:
        try:
            return factory()
        except (OSError, ProtocolError) as error:
            last = error
            time.sleep(.3)
    raise ProtocolError(f'USB 再接続を確認できませんでした: {last}')


def update(mouse, progress):
    """Called only on the HID owner thread after explicit GUI confirmation.

    This closes the supplied mouse after entering DFU. Recovery flashing is not
    offered: boot identity/recovery behavior has not been validated on hardware.
    """
    from .system import ghub_running
    candidate = current_candidate()
    info = inspect(mouse)
    if not info['eligible']:
        raise ProtocolError(info['reason']+' 有線接続と検証済みファイルが必要です。')
    if ghub_running():
        raise ProtocolError('更新前に G HUB を終了してください。')
    image = validate_package(package_path(candidate).read_bytes(), candidate)
    if info['entity'] != image[0] or info['unit'] in ('00000000', 'ffffffff'):
        raise ProtocolError('更新対象のエンティティまたは本体 ID が一致しません。')
    flags = mouse.call(0x00c2)
    if len(flags) < 3 or flags[2] & 1:
        raise ProtocolError('本体が署名付き更新を許可していません。')
    previous = CACHE / 'update-journal.json'
    if previous.exists() and json.loads(previous.read_text(encoding='utf-8')).get('state') not in ('complete','aborted-before-transfer'):
        raise ProtocolError('未完了の更新記録があります。状態を調査するまで再更新できません。')
    # Settings backup is not a backup of the firmware or a recovery guarantee.
    backup = str(mouse.backup())
    journal = {**info, 'sha256': candidate['image_sha256'], 'target_version':candidate['version'],
               'depot_sha256':candidate['sha256'], 'settings_backup': backup}

    def record(state):
        if state == 'failed': journal['failed_at'] = journal.get('state')
        journal['state'] = state
        path = CACHE / 'update-journal.tmp'
        with path.open('w', encoding='utf-8') as stream:
            json.dump(journal, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        path.replace(CACHE / 'update-journal.json')

    record('entering-dfu')
    boot = None
    import ctypes
    # Keep Windows awake for this owner thread; restore its previous requirement.
    power_state = ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    if not power_state:
        record('failed')
        raise ProtocolError('更新中の自動スリープを抑止できませんでした。')
    try:
        progress('ブートローダーへ切り替え中', 0)
        # Reset can remove the interface before its reply arrives. No retry.
        try:
            mouse.call(0x00c2, 1, b'\x01\0\0\0DFU')
        except (OSError, ProtocolError):
            pass
        mouse.close()
        boot = wait_device(open_boot)
        # Never select a different mouse just because its boot PID matches.
        if identity(boot)['unit'] != info['unit']:
            raise ProtocolError('ブートローダーの本体 ID が一致しません。書き込みを中止しました。')
        record('transferring')
        transport = DfuTransport(boot.h, boot.feature(0x00d0))
        transfer(transport, image, progress)
        record('restarting')
        progress('本体を再起動し、バージョンを検証中', 100)
        transport.send(5, bytes([info['entity']]))
        boot.close()
        boot = None
        with wait_device(Mouse) as current:
            actual = identity(current)
            if (actual['unit'] != info['unit'] or not actual['wired'] or
                    version_tuple(actual.get('version','0.0.0')) != version_tuple(candidate['version'])):
                raise ProtocolError('再起動後の本体とバージョンを確認できません。成功とは判定しません。')
        record('complete')
        progress('更新完了・本体バージョン確認済み', 100)
    except Exception:
        record('failed')
        raise
    finally:
        try:
            if boot:
                boot.close()
        finally:
            ctypes.windll.kernel32.SetThreadExecutionState(power_state)
