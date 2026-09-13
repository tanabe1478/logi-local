# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import unittest
import copy
import queue
from unittest.mock import patch, Mock
from logilocal.bridge import BridgeEngine
from logilocal.config import DEFAULT


class BridgeTests(unittest.TestCase):
    def runtime_engine(self):
        engine=BridgeEngine.__new__(BridgeEngine)
        engine.config=copy.deepcopy(DEFAULT)
        engine.enabled=True
        engine.forced_profile=None
        engine.profile=None
        engine.events=queue.SimpleQueue()
        engine.mouse=Mock()
        engine.apply=Mock()
        return engine

    def test_runtime_apply_reports_success_only_after_readback(self):
        engine=self.runtime_engine()
        engine.mouse.status.return_value={'dpi':1600,'report_rate_ms':1}
        with patch('logilocal.bridge.foreground_exe',return_value='desktop.exe'):
            result=engine.dispatch('runtime-set',[{}])
        self.assertTrue(result['device_applied'])
        engine.apply.assert_called_once_with(engine.config['profiles'][0])

    def test_runtime_readback_mismatch_is_an_error(self):
        engine=self.runtime_engine()
        engine.mouse.status.return_value={'dpi':800,'report_rate_ms':1}
        with patch('logilocal.bridge.foreground_exe',return_value='desktop.exe'):
            with self.assertRaises(ValueError): engine.dispatch('runtime-set',[{}])

    def test_runtime_without_mouse_does_not_enable(self):
        engine=self.runtime_engine()
        engine.enabled=False
        engine.mouse=None
        with self.assertRaises(ValueError): engine.dispatch('runtime-set',[{'enabled':True}])
        self.assertFalse(engine.enabled)

    def test_onboard_stale_confirmation_does_not_write(self):
        engine=self.runtime_engine()
        with patch('logilocal.bridge.load',return_value={'profiles':[]}), patch('logilocal.runtime.Engine.command') as command:
            with self.assertRaises(ValueError):engine.dispatch('onboard-expected',[engine.config['profiles'][0]])
            command.assert_not_called()
    def test_atomic_save_rejects_stale_base(self):
        engine = BridgeEngine.__new__(BridgeEngine)
        with patch('logilocal.bridge.load', return_value={'dpi':3200}), patch('logilocal.bridge.save') as save:
            with self.assertRaises(ValueError):
                engine.dispatch('config-save-expected', [{'dpi':800}, {'dpi':1600}])
            save.assert_not_called()

    def test_atomic_save_reloads_engine(self):
        engine = BridgeEngine.__new__(BridgeEngine)
        with patch('logilocal.bridge.load', side_effect=[{'dpi':1600},{'dpi':800}]), \
                patch('logilocal.bridge.save') as save, patch('logilocal.runtime.Engine.command') as command:
            self.assertEqual(engine.dispatch('config-save-expected',[{'dpi':800},{'dpi':1600}]),{'dpi':800})
            save.assert_called_once_with({'dpi':800})
            command.assert_called_once_with('reload', ())

    def test_unknown_operation_never_reaches_engine(self):
        engine = BridgeEngine.__new__(BridgeEngine)
        with patch('logilocal.runtime.Engine.command') as command:
            with self.assertRaises(ValueError): engine.dispatch('shell', ['anything'])
            command.assert_not_called()
