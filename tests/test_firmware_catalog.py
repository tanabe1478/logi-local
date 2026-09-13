# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from logilocal import firmware as fw, firmware_catalog as catalog
from test_firmware import depot


def package(version='22.03.01', bad_target=False):
    image = b'\1\1MPM22_D0' + b'\0'*22
    metadata = {'contents':[{'version':version, 'interfaceInfos':[
        {'interfaceId':pid, 'deviceInterfaceType':'DEVIO','updatable':True}
        for pid in (['046d_c091','046d_4086','046d_aaf6'] if bad_target else
                    ['046d_c090','046d_4086','046d_aaf6'])],
        'binaryFileKey':{'key':'firmware','hash':hashlib.sha256(image).hexdigest()}}]}
    manifest = {'resources':[{'key':'firmware','src':'image.dfu'}]}
    data = depot(['dfu.json','manifest.json','image.dfu'],
                 [json.dumps(metadata).encode(),json.dumps(manifest).encode(),image])
    return data, {'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                  'source':catalog.DETAILS_URL, 'url':fw.URL}


def details(candidate):
    return {'appId':'ghub13','platform':'win','channel':'public','buildId':123,
            'depots':[{'name':'g703_hero_dfu','size':candidate['size'],
                       'mac':candidate['sha256'],'url':candidate['url'].removeprefix(catalog.ORIGIN)}]}


class CatalogTests(unittest.TestCase):
    def test_new_official_version_parsed_without_code_change(self):
        data, candidate = package()
        image, value = catalog.parse_package(data,candidate,fw.unpack_depot)
        self.assertEqual(value['version'],'22.03.01')
        self.assertEqual(len(image),32)

    def test_other_model_rejected(self):
        data, candidate = package(bad_target=True)
        with self.assertRaises(ValueError): catalog.parse_package(data,candidate,fw.unpack_depot)

    def test_corrupted_package_rejected(self):
        data, candidate = package()
        with self.assertRaises(ValueError): catalog.parse_package(data[:-1]+b'x',candidate,fw.unpack_depot)

    def test_catalog_rejects_foreign_url_duplicate_and_wrong_channel(self):
        _, candidate = package()
        for kind in ('url','duplicate','channel'):
            value=details(candidate)
            if kind=='url': value['depots'][0]['url']='https://example.com/firmware.depot'
            if kind=='duplicate': value['depots']*=2
            if kind=='channel': value['channel']='private'
            with self.assertRaises(ValueError): catalog.select_depot(value)

    def test_download_never_opens_other_origin(self):
        with patch('urllib.request.build_opener') as opener:
            with self.assertRaises(ValueError): catalog.download('https://example.com/file',100)
            opener.assert_not_called()

    def test_refresh_publishes_only_validated_candidate(self):
        data, candidate = package()
        with tempfile.TemporaryDirectory() as directory:
            cache=Path(directory)
            with patch.object(catalog,'download',side_effect=[json.dumps(details(candidate)).encode(),data]):
                result=catalog.refresh(cache,fw.unpack_depot)
            self.assertEqual(result['version'],'22.03.01')
            before=(cache/'catalog.json').read_bytes()
            with patch.object(catalog,'download',side_effect=[json.dumps(details(candidate)).encode(),b'bad']):
                with self.assertRaises(ValueError): catalog.refresh(cache,fw.unpack_depot)
            self.assertEqual((cache/'catalog.json').read_bytes(),before)
            with patch.object(fw,'CACHE',cache):
                current=fw.current_candidate()
                self.assertEqual(current['version'],'22.03.01')
                self.assertEqual(fw.validate_package(fw.package_path(current).read_bytes(),current)[:2],b'\1\1')
