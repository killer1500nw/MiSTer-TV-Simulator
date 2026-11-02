import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.player import h264sps as sps


def make_sps(width, height, crop=None):
    """A minimal Baseline-profile SPS NAL for a progressive picture (width and height multiples of 16)."""
    out = sps.Out()
    out.u(66, 8)
    out.u(0, 8)
    out.u(30, 8)
    out.ue(0)            # sps id
    out.ue(0)            # log2_max_frame_num_minus4
    out.ue(2)            # poc type
    out.ue(1)            # max ref frames
    out.u(0, 1)
    out.ue(width // 16 - 1)
    out.ue(height // 16 - 1)
    out.u(1, 1)          # frame_mbs_only
    out.u(1, 1)          # direct_8x8_inference
    if crop:
        out.u(1, 1)
        for v in crop:
            out.ue(v)
    else:
        out.u(0, 1)
    out.u(0, 1)          # no VUI
    out.u(1, 1)          # stop bit
    return bytes([0x67]) + sps.escape(out.tobytes())


def visible(nal):
    return sps.visible(sps.parse(nal))


class T(unittest.TestCase):
    def test_widescreen_trimmed_to_fill(self):
        self.assertEqual(visible(sps.crop_shape(make_sps(1280, 720), [(4, 3)])), (960, 720))

    def test_14_9(self):
        w, h = visible(sps.crop_shape(make_sps(1280, 720), [(14, 9)]))
        self.assertEqual(h, 720)
        self.assertAlmostEqual(w / h, 14 / 9, delta=0.02)

    def test_letterboxed_frame_zoomed_to_fill(self):
        # a 4:3 frame (640x480) holding a 16:9 picture with baked-in bars: remove the bars, then fill 4:3
        self.assertEqual(visible(sps.crop_shape(make_sps(640, 480), [(16, 9)])), (640, 360))
        self.assertEqual(visible(sps.crop_shape(make_sps(640, 480), [(16, 9), (4, 3)])), (480, 360))

    def test_scope_bars(self):
        w, h = visible(sps.crop_shape(make_sps(1280, 720), [(47, 20), (4, 3)]))
        self.assertAlmostEqual(w / h, 4 / 3, delta=0.02)
        self.assertLess(h, 720)

    def test_leaves_a_matching_picture_alone(self):
        nal = make_sps(640, 480)
        self.assertIs(sps.crop_shape(nal, [(4, 3)]), nal)

    def test_existing_crop_is_kept_and_extended(self):
        # 1920x1088 coded, cropped to 1080 at the bottom: fill must start from the visible 1920x1080
        w, h = visible(sps.crop_shape(make_sps(1920, 1088, (0, 0, 0, 4)), [(4, 3)]))
        self.assertEqual(h, 1080)
        self.assertAlmostEqual(w / h, 4 / 3, delta=0.02)

    def test_access_unit_with_a_list_of_steps(self):
        au = b'\x00\x00\x00\x01' + make_sps(1280, 720) + b'\x00\x00\x01\x65\x88\x84'
        out = sps.crop_access_unit(au, [(4, 3)])
        self.assertNotEqual(out, au)
        self.assertTrue(out.endswith(b'\x00\x00\x01\x65\x88\x84'))
        nal = out[4:out.index(b'\x00\x00\x01\x65')]
        self.assertEqual(visible(nal), (960, 720))


if __name__ == '__main__':
    unittest.main()
