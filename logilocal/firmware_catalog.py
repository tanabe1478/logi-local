# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
"""Official public G HUB catalog access, without installing/running G HUB."""
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

ORIGIN = 'https://updates.ghub.logitechg.com'
DETAILS_URL = ORIGIN + '/pipeline/v2/update/ghub13/win/public/details.json'
MAX_DEPOT = 2_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('公式配布元のリダイレクトは未対応です。')


def download(url, maximum):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'updates.ghub.logitechg.com' or parsed.query or parsed.fragment:
        raise ValueError('許可されていない配布元です。')
    with urllib.request.build_opener(NoRedirect).open(url, timeout=30) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('公式データが上限サイズを超えています。')
    return data


def select_depot(details):
    if (details.get('appId') != 'ghub13' or details.get('platform') != 'win' or
            details.get('channel') != 'public' or type(details.get('buildId')) is not int):
        raise ValueError('公式更新カタログの対象が一致しません。')
    matches = [d for d in details.get('depots', []) if d.get('name') == 'g703_hero_dfu']
    if len(matches) != 1:
        raise ValueError('G703 HERO の更新候補を一意に特定できません。')
    depot = matches[0]
    if (type(depot.get('size')) is not int or not 0 < depot['size'] <= MAX_DEPOT or
            not re.fullmatch(r'[a-fA-F0-9]{64}', depot.get('mac', '')) or
            not re.fullmatch(r'/depots/[a-fA-F0-9-]{36}/g703_hero_dfu\.depot', depot.get('url', ''))):
        raise ValueError('公式更新候補の形式が不正です。')
    return {'url': ORIGIN + depot['url'], 'size': depot['size'], 'sha256': depot['mac'].lower(),
            'build_id': details['buildId'], 'source': DETAILS_URL,
            'checked_at': datetime.now(timezone.utc).isoformat()}


def parse_package(data, candidate, unpack):
    if len(data) != candidate['size'] or hashlib.sha256(data).hexdigest() != candidate['sha256']:
        raise ValueError('公式カタログのパッケージ SHA-256 と一致しません。')
    files = unpack(data)
    contents = json.loads(files['dfu.json'])['contents']
    if len(contents) != 1:
        raise ValueError('複数イメージの更新は未対応です。')
    metadata = contents[0]
    if not re.fullmatch(r'\d{1,2}\.\d{1,2}\.\d{1,4}', metadata.get('version', '')):
        raise ValueError('未知の更新バージョン形式です。')
    interfaces = metadata.get('interfaceInfos', [])
    if {i.get('interfaceId') for i in interfaces} != {'046d_c090','046d_4086','046d_aaf6'}:
        raise ValueError('G703 HERO 以外のイメージは更新できません。')
    if not all(i.get('deviceInterfaceType') == 'DEVIO' for i in interfaces):
        raise ValueError('未知の更新インターフェースです。')
    if not any(i['interfaceId'] == '046d_c090' and i.get('updatable') for i in interfaces):
        raise ValueError('有線本体の更新に対応していません。')
    key = metadata['binaryFileKey']['key']
    manifest = json.loads(files['manifest.json'])
    # The official resource manifest maps the metadata's key to the image path.
    entries = manifest.get('resources', [])
    if isinstance(entries, dict):
        entries = [dict(value, key=name) for name,value in entries.items()]
    matches = [entry for entry in entries if entry.get('key') == key]
    if len(matches) != 1:
        raise ValueError('更新イメージを一意に特定できません。')
    name = matches[0]['src']
    image = files[name]
    digest = metadata['binaryFileKey']['hash'].lower()
    if (not re.fullmatch(r'[0-9a-f]{64}', digest) or hashlib.sha256(image).hexdigest() != digest or
            not image or len(image) % 16 or image[:10] != b'\x01\x01MPM22_D0'):
        raise ValueError('G703 HERO の署名付きイメージ形式または SHA-256 が一致しません。')
    if candidate.get('version') and candidate['version'] != metadata['version']:
        raise ValueError('保存済み候補とイメージのバージョンが一致しません。')
    return image, {**candidate, 'version': metadata['version'], 'image_sha256': digest,
                   'image_name': name, 'image_size': len(image)}


def refresh(cache, unpack):
    candidate = select_depot(json.loads(download(DETAILS_URL, 3_000_000)))
    data = download(candidate['url'], candidate['size'])
    _, candidate = parse_package(data, candidate, unpack)
    cache.mkdir(parents=True, exist_ok=True)
    # Content-addressed file first; candidate is published only after validation.
    package = cache / (candidate['sha256'] + '.depot')
    temporary = package.with_suffix('.tmp')
    temporary.write_bytes(data)
    temporary.replace(package)
    temporary = cache / 'catalog.tmp'
    temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(cache / 'catalog.json')
    return candidate
