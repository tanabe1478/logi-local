# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import copy
import json
import struct
import threading
import time
import unittest

from logilocal.config import DEFAULT,keys,match_profile,validate
from logilocal.device import Mouse,ProtocolError,crc,valid_sector,patch_profile,decode_profile,battery_percent
from logilocal.onboard import binding
from logilocal.wininput import Output, INPUT
from logilocal.runtime import MacroPlayer,Engine


def sector(size=255):
    data=bytearray([255]*size)
    data[:3]=bytes([1,2,0])
    struct.pack_into('<5H',data,3,400,800,1600,3200,0)
    for i in range(5):data[32+i*4:36+i*4]=binding(f'mouse:{i+1}')
    data[52:56]=binding('dpi-cycle')
    data[-2:]=crc(data[:-2]).to_bytes(2,'big')
    return bytes(data)


class ProtocolTests(unittest.TestCase):
    def test_crc_known_vector(self):
        self.assertEqual(crc(b'123456789'),0x29B1)

    def test_preserve_unknown_bytes(self):
        old=sector();new=patch_profile(old,dpi=2400,buttons={3:binding('key:ctrl+c')})
        self.assertTrue(valid_sector(new))
        changed={i for i,(a,b) in enumerate(zip(old,new)) if a!=b}
        self.assertTrue(changed.issubset({7,8,44,45,46,47,253,254}))
        self.assertEqual(decode_profile(new)['dpis'],[400,800,2400,3200,0])

    def test_bad_crc_rejected(self):
        corrupt=bytearray(sector());corrupt[10]^=1
        with self.assertRaises(ProtocolError):patch_profile(corrupt,dpi=1200)

    def test_read_255_tail_without_duplicate(self):
        expected=sector()
        class Mock:
            def describe(self):return {'sector_size':255}
            def call(self,fid,fn,parameters):
                s,offset=struct.unpack('>HH',parameters)
                assert s==1 and offset<=239
                return expected[offset:offset+16]
        self.assertEqual(Mouse.read_sector(Mock(),1),expected)

    def test_read_256_tail(self):
        expected=sector(256)
        class Mock:
            def describe(self):return {'sector_size':256}
            def call(self,fid,fn,parameters):
                _,offset=struct.unpack('>HH',parameters)
                return expected[offset:offset+16]
        self.assertEqual(Mouse.read_sector(Mock(),1),expected)

    def test_exact_bindings(self):
        self.assertEqual(binding('key:ctrl+c').hex(),'80020106')
        self.assertEqual(binding('key:ctrl').hex(),'80020100')
        self.assertEqual(binding('mouse:5').hex(),'80010010')
        with self.assertRaises(ValueError):binding('macro:test')

    def test_battery_monotonic(self):
        values=[battery_percent(v) for v in range(3400,4300)]
        self.assertEqual(values,sorted(values))
        self.assertEqual(battery_percent(3922),70)

    def test_filters_notifications_and_foreign_responses(self):
        class H:
            def write(self,p):
                self.sent=p
                self.responses=[b'\x11\x01\x09\x00'+bytes(16),b'\x11\x01\x01\x19'+bytes(16),
                                bytes([0x11,1,p[2],p[3]])+b'OK'+bytes(14)]
                return 20
            def read(self,*args):return self.responses.pop(0)
        m=Mouse.__new__(Mouse);m.h=H();m.swid=8;events=[];m.on_event=events.append
        self.assertEqual(m.request(3,1)[:2],b'OK')
        self.assertEqual(len(events),1)


class ConfigTests(unittest.TestCase):
    def test_imported_application_double_slashes(self):
        c=copy.deepcopy(DEFAULT);p=copy.deepcopy(c['profiles'][0]);p.update(name='game',apps=[r'C:\\Games\\game.exe'])
        c['profiles'].append(p)
        self.assertIs(match_profile(c,r'c:\Games\game.exe'),p)
        self.assertIs(match_profile(c,r'C:\Other\game.exe'),c['profiles'][0])

    def test_reject_unbalanced_macro(self):
        c=copy.deepcopy(DEFAULT);c['macros']['bad']={'steps':[{'key':'ctrl','down':True}]}
        with self.assertRaises(ValueError):validate(c)

    def test_reject_unsupported_key_and_missing_macro(self):
        c=copy.deepcopy(DEFAULT);c['profiles'][0]['buttons']['4']='macro:missing'
        with self.assertRaises(ValueError):validate(c)
        with self.assertRaises(ValueError):keys('unknownkey')

    def test_deepcopy_default_stays_valid(self):
        validate(copy.deepcopy(DEFAULT))


class MacroTests(unittest.TestCase):
    def test_overlapping_owners(self):
        events=[];o=Output(lambda *a:events.append(a))
        o.chord('one','ctrl',True);o.chord('two','ctrl',True)
        o.release('one');self.assertEqual(events,[('key',162,True)])
        o.release('two');self.assertEqual(events[-1],('key',162,False))

    def test_cancel_interrupts_wait_releases_key(self):
        events=[];pressed=threading.Event()
        def sender(*args):events.append(args);pressed.set()
        o=Output(sender);p=MacroPlayer(o)
        p.trigger('5',{'mode':'hold','steps':[{'key':'space','down':True},{'wait':60000},{'key':'space','down':False}]},True)
        self.assertTrue(pressed.wait(1));start=time.monotonic();p.stop()
        self.assertLess(time.monotonic()-start,1)
        self.assertEqual(events,[('key',32,True),('key',32,False)])
        self.assertEqual(o.owners,{})

    def test_once_sequence_exact_order(self):
        events=[];o=Output(lambda *a:events.append(a));p=MacroPlayer(o)
        p.trigger('5',{'mode':'once','steps':[{'mouse':2,'down':True},{'mouse':2,'down':False},
                                           {'key':'space','down':True},{'key':'space','down':False}]},True)
        until=time.monotonic()+1
        while p.jobs and time.monotonic()<until:time.sleep(.005)
        self.assertEqual(events,[('mouse',2,True),('mouse',2,False),('key',32,True),('key',32,False)])

    def test_button_release_uses_original_action(self):
        import queue
        e=Engine.__new__(Engine);e.events=queue.SimpleQueue();e.commands=queue.SimpleQueue();e.mask=0
        e.enabled=True;e.held={};e.profile={'buttons':{'4':'key:ctrl'}};e.config={'macros':{}}
        events=[];e.output=Output(lambda *a:events.append(a));e.mouse=type('M',(),{'feature':lambda _,fid:9})()
        e.on_packet(bytes.fromhex('110109000008'))
        e.profile={'buttons':{'4':'key:shift'}}
        e.on_packet(bytes.fromhex('110109000000'))
        self.assertEqual(events,[('key',162,True),('key',162,False)])


if __name__=='__main__':unittest.main()
