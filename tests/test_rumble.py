import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.player import rumble


class T(unittest.TestCase):
    def test_the_gain_event_is_an_ff_gain_input_event(self):
        ev = rumble.gain_event(0)
        self.assertEqual(len(ev), struct.calcsize('llHHi'))
        self.assertEqual(struct.unpack('llHHi', ev)[2:], (0x15, 0x60, 0))
        self.assertEqual(struct.unpack('llHHi', rumble.gain_event(0xFFFF))[4], 0xFFFF)

    def test_only_pads_that_can_rumble_are_found(self):
        root = Path(tempfile.mkdtemp())
        for name, ff in (('event0', '0'), ('event4', '7030000 0 0'), ('event6', '7030000 0 0'), ('event7', '0')):
            d = root / name / 'device' / 'capabilities'
            d.mkdir(parents=True)
            (d / 'ff').write_text(ff + '\n')
        (root / 'event9').mkdir()                                    # no capabilities file at all
        found = rumble.ff_devices(str(root), '/dev/input')
        self.assertEqual([os.path.basename(p) for p in found], ['event4', 'event6'])

    def test_a_missing_device_is_skipped(self):
        self.assertEqual(rumble.set_gain(0, ['/dev/input/does-not-exist']), 0)


if __name__ == '__main__':
    unittest.main()
