"""TIME formatting must remain usable by legacy batch arithmetic."""
from datetime import datetime
import io
from pathlib import Path
import unittest
from pycmd import Runtime

ROOT=Path(__file__).resolve().parents[1]

class DynamicTimeTests(unittest.TestCase):
    def test_hours_use_space_padding_and_keep_substring_positions(self):
        rt=Runtime()
        for hour in range(24):
            rt.state.clock=datetime(2026,10,16,hour,1,26,409999)
            self.assertEqual(rt.state.dynamic('TIME'),f'{hour:2d}:01:26.40')
        rt.state.env['TIME']='custom'
        self.assertEqual(rt.state.dynamic('time'),'custom')

