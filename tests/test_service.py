# SPDX-License-Identifier: GPL-3.0-or-later
import json
import queue
import secrets
import threading
import unittest
from multiprocessing.connection import Client, Listener
from unittest.mock import Mock

from logilocal.service import Service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = Mock()
        self.engine.commands = queue.Queue()
        self.engine.firmware_busy = False
        self.service = Service(self.engine)
        self.address = rf'\\.\pipe\LogiLocal-test-{secrets.token_hex(12)}'
        self.key = secrets.token_bytes(32)
        self.listener = Listener(self.address, family='AF_PIPE', authkey=self.key)
        self.connections = []

    def tearDown(self):
        for connection in self.connections: connection.close()
        self.listener.close()

    def connect(self):
        def accept():
            self.service.attach(self.listener.accept())
        threading.Thread(target=accept,daemon=True).start()
        connection = Client(self.address,family='AF_PIPE',authkey=self.key)
        self.connections.append(connection)
        return connection

    def read(self, connection):
        self.assertTrue(connection.poll(3), 'pipe response timed out')
        return json.loads(connection.recv_bytes())

    def test_reconnect_preserves_engine_and_replays_state(self):
        self.service.publish({'event':'enabled','value':True})
        first = self.connect()
        self.assertEqual(self.read(first)['value'],True)
        self.assertEqual(self.read(first)['event'],'ready')
        first.close()
        self.service.publish({'event':'profile','value':'Game'})
        second = self.connect()
        self.assertEqual(self.read(second),{'event':'enabled','value':True})
        self.assertEqual(self.read(second),{'event':'profile','value':'Game'})
        self.engine.stop.assert_not_called()

    def test_gui_shutdown_does_not_stop_hid_owner(self):
        client = self.connect()
        self.read(client)
        client.send_bytes(b'{"id":"1","op":"shutdown"}')
        self.assertEqual(self.read(client),{'id':'1','result':True})
        self.engine.stop.assert_not_called()

    def test_replies_are_scoped_to_original_connection(self):
        first,second=self.connect(),self.connect()
        self.read(first); self.read(second)
        first.send_bytes(b'{"id":"1","op":"runtime-get"}')
        _,(request,) = self.engine.commands.get(timeout=3)
        first.close()
        self.service.publish({'id':request['id'],'result':'old-response'})
        self.service.publish({'event':'status','value':{'dpi':800}})
        self.assertEqual(self.read(second),{'event':'status','value':{'dpi':800}})

    def test_tray_stop_refuses_active_flash(self):
        self.engine.firmware_busy=True
        self.assertFalse(self.service.stop())
        self.engine.stop.assert_not_called()

    def test_tray_stop_waits_for_queued_commands(self):
        def barrier():
            name,args=self.engine.commands.get(timeout=3)
            self.assertEqual(name,'barrier')
            args[0].set()
        thread=threading.Thread(target=barrier)
        thread.start()
        self.assertTrue(self.service.stop())
        thread.join()
        self.engine.stop.assert_called_once()


if __name__ == '__main__': unittest.main()
