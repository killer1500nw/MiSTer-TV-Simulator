import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.verdict import verdict


def v(**kw):
    base = dict(Codec='h264', Profile='High', BitDepth=8, PixelFormat='yuv420p', IsInterlaced=False,
                Width=656, Height=432, RealFrameRate=29.97, BitRate=1_450_000)
    base.update(kw)
    return base


class T(unittest.TestCase):
    def test_spike_files(self):
        self.assertEqual(verdict(v()), (True, 'ok'))                                     # Beavis: played direct
        self.assertFalse(verdict(v(Profile='Constrained Baseline', Width=490, Height=480))[0])   # Captain Planet: no picture
        self.assertFalse(verdict(v(Codec='hevc', Width=1920, Height=1080))[0])           # Simpsons: transcoded

    def test_limits(self):
        self.assertTrue(verdict(v(Width=1280, Height=720, RealFrameRate=30))[0])         # 720p30
        self.assertFalse(verdict(v(Width=1280, Height=720, RealFrameRate=60))[0])        # 720p60
        self.assertTrue(verdict(v(Width=720, Height=480, RealFrameRate=60))[0])          # 480p60
        self.assertTrue(verdict(v(Width=720, Height=576, RealFrameRate=50))[0])          # PAL 50 fps
        self.assertFalse(verdict(v(BitRate=9_000_000))[0])
        self.assertFalse(verdict(v(IsInterlaced=True))[0])
        self.assertFalse(verdict(v(BitDepth=10))[0])
        self.assertFalse(verdict(None)[0])


if __name__ == "__main__":
    unittest.main()
