# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import json
import struct
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from logilocal import firmware as fw
from logilocal.device import ProtocolError


def depot(entries, bodies):
    metadata = json.dumps({'files':[{'name':name} for name in entries]}).encode()
    return b'\x10\x01\x17\x20'+struct.pack('<I',len(metadata))+metadata+b''.join(
        struct.pack('<I',len(body))+body for body in bodies)


class PackageTests(unittest.TestCase):
    def test_parser_does_not_extract_paths(self):
        self.assertEqual(fw.unpack_depot(depot(['../unused'],[b'abc'])),{'../unused':b'abc'})

    def test_truncated_and_trailing_data(self):
        data = depot(['a'],[b'abc'])
        for bad in (data[:-1],data+b'x',data[:7],b'nope'+data[4:]):
            with self.assertRaises(ValueError): fw.unpack_depot(bad)

    def test_duplicate_entries(self):
        with self.assertRaises(ValueError): fw.unpack_depot(depot(['a','a'],[b'1',b'2']))

    def test_unapproved_package_rejected(self):
        with self.assertRaises(ValueError): fw.validate_package(b'\0'*fw.DEPOT_SIZE)

    def test_version_numeric_comparison(self):
        self.assertGreater(fw.version_tuple('22.10.01'),fw.version_tuple('22.02.15'))
        with self.assertRaises(ValueError): fw.version_tuple('22.a.15')

    def test_redirect_rejected(self):
        with self.assertRaises(ValueError):
            fw.NoRedirect().redirect_request(None,None,302,'',{},'https://example.com')


def fake_mouse(version=b'\x22\x02\x00\x15'):
    mouse = Mock()
    mouse.info = {'product_id':0xc090}
    # Synthetic identity; never include a user's hardware ID in fixtures.
    mouse.call.side_effect = lambda fid, fn=0, data=b'': (
        bytes.fromhex('0112345678000c4086c090000000000000') if fn == 0 else
        b'\0MPM'+version+b'\x01'+b'\0'*7)
    return mouse


class PreflightTests(unittest.TestCase):
    def test_actual_format_bcd(self):
        self.assertEqual(fw.identity(fake_mouse())['version'],'22.02.15')

    def test_unknown_version_format(self):
        with self.assertRaises(ProtocolError): fw.identity(fake_mouse(b'\xaa\x02\x00\x15'))

    def test_equal_newer_and_wireless_not_eligible(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(fw,'CACHE',Path(directory)):
            for version in (b'\x22\x02\x00\x15', b'\x22\x03\x00\x15'):
                self.assertFalse(fw.inspect(fake_mouse(version))['eligible'])
            wireless = fake_mouse(b'\x22\x01\x00\x01')
            wireless.info['product_id'] = 0xc539
            self.assertFalse(fw.inspect(wireless)['eligible'])

    def test_equal_version_update_never_enters_dfu(self):
        mouse = fake_mouse()
        with tempfile.TemporaryDirectory() as directory, patch.object(fw,'CACHE',Path(directory)):
            with self.assertRaises(ProtocolError): fw.update(mouse,Mock())
        mouse.backup.assert_not_called()
        self.assertTrue(all(call.args[0] == 3 for call in mouse.call.call_args_list))


class FakeHid:
    def __init__(self, replies):
        self.replies, self.writes = list(replies), []

    def write(self, packet):
        self.writes.append(packet)
        return len(packet)

    def read(self, size, timeout):
        if not self.replies: raise OSError('disconnected')
        return self.replies.pop(0)


def reply(status, counter=1, address=0x49, feature=7):
    return bytes([0x11,0xff,feature,address])+counter.to_bytes(4,'big')+bytes([status])+b'\0'*11


class TransportTests(unittest.TestCase):
    def test_wait_event_and_status_high_bit(self):
        handle = FakeHid([reply(3),reply(0x81,address=0)])
        self.assertEqual(fw.DfuTransport(handle,7).packet(4,b'x'*16),1)
        self.assertEqual(len(handle.writes),1)

    def test_foreign_response_ignored(self):
        handle = FakeHid([reply(1,feature=8),reply(1,address=0x48),reply(1)])
        fw.DfuTransport(handle,7).packet(4,b'x'*16)

    def test_async_error_stops_without_retry(self):
        handle = FakeHid([reply(3),reply(0x20,address=0)])
        with self.assertRaises(ProtocolError): fw.DfuTransport(handle,7).packet(4,b'x'*16)
        self.assertEqual(len(handle.writes),1)

    def test_mismatched_counter_stops(self):
        handle = FakeHid([reply(3),reply(1,counter=2,address=0)])
        with self.assertRaises(ProtocolError): fw.DfuTransport(handle,7).packet(4,b'x'*16)

    def test_short_hid_error(self):
        handle = FakeHid([bytes([0x10,0xff,0xff,7,0x49,2,0])])
        with self.assertRaises(ProtocolError): fw.DfuTransport(handle,7).packet(4,b'x'*16)

    def test_disconnect_not_retried(self):
        handle = FakeHid([])
        with self.assertRaises(OSError): fw.DfuTransport(handle,7).packet(4,b'x'*16)
        self.assertEqual(len(handle.writes),1)

    def test_packet_sequence_and_entire_stream(self):
        transport, progress = Mock(), Mock()
        image = bytes(range(128))
        fw.transfer(transport,image,progress)
        calls = transport.packet.call_args_list
        self.assertEqual([call.args[0] for call in calls],[4,1,2,3,0,1,2,3])
        self.assertEqual(b''.join(call.args[1] for call in calls),image)
        self.assertEqual(progress.call_args.args[1],100)

    def test_stop_stream_on_error(self):
        transport = Mock()
        transport.packet.side_effect = [1,ProtocolError('write failed')]
        with self.assertRaises(ProtocolError): fw.transfer(transport,b'x'*64,Mock())
        self.assertEqual(transport.packet.call_count,2)


class UpdateTests(unittest.TestCase):
    def run_update(self, wrong_boot=False, wrong_version=False, transfer_error=False):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            cache = Path(directory)
            (cache/'g703_hero.depot').write_bytes(b'synthetic')
            stack.enter_context(patch.object(fw,'CACHE',cache))
            info = {'unit':'12345678','entity':1,'version':'22.01.01','wired':True,
                    'eligible':True,'reason':'ready'}
            stack.enter_context(patch.object(fw,'inspect',return_value=info))
            stack.enter_context(patch.object(fw,'validate_package',return_value=b'\1'+b'x'*31))
            stack.enter_context(patch('logilocal.system.ghub_running',return_value=False))
            stack.enter_context(patch('ctypes.windll.kernel32.SetThreadExecutionState',return_value=0x80000000))
            mouse, boot, current = Mock(), Mock(), Mock()
            mouse.call.return_value = b'\0'*16
            mouse.backup.return_value = 'synthetic-backup'
            current.__enter__ = Mock(return_value=current)
            current.__exit__ = Mock(return_value=False)
            stack.enter_context(patch.object(fw,'wait_device',side_effect=[boot,current]))
            stack.enter_context(patch.object(fw,'identity',side_effect=[
                {'unit':'87654321' if wrong_boot else '12345678'},
                {'unit':'12345678','wired':True,'version':'22.01.01' if wrong_version else fw.VERSION}]))
            stream = stack.enter_context(patch.object(fw,'transfer'))
            if transfer_error: stream.side_effect = ProtocolError('synthetic failure')
            transport = stack.enter_context(patch.object(fw,'DfuTransport'))
            if wrong_boot or wrong_version or transfer_error:
                with self.assertRaises(ProtocolError): fw.update(mouse,Mock())
            else:
                fw.update(mouse,Mock())
            state = json.loads((cache/'update-journal.json').read_text(encoding='utf-8'))['state']
            return state, stream.call_count, transport.return_value.send.call_count

    def test_success_requires_reboot_verification(self):
        self.assertEqual(self.run_update(),('complete',1,1))

    def test_wrong_boot_identity_never_writes(self):
        self.assertEqual(self.run_update(wrong_boot=True),('failed',0,0))

    def test_old_version_after_reboot_not_success(self):
        self.assertEqual(self.run_update(wrong_version=True),('failed',1,1))

    def test_failed_stream_does_not_restart(self):
        self.assertEqual(self.run_update(transfer_error=True),('failed',1,0))


if __name__ == '__main__':
    unittest.main()
