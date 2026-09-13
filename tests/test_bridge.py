# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Logi Local contributors
import unittest
from unittest.mock import patch
from logilocal.bridge import BridgeEngine


class BridgeTests(unittest.TestCase):
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
