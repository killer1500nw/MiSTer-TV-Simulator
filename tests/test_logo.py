import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.player.app import App
from tvsim.player.overlay import Canvas
from tvsim.studio import server
from tvsim.studio.compile import compile_all, logo_meta

RGBA = bytes([255, 0, 0, 255,      # opaque red
              0, 255, 0, 200,      # mostly opaque green
              0, 0, 255, 60,       # mostly transparent blue
              9, 9, 9, 0])         # fully transparent


class T(unittest.TestCase):
    def test_pixels_keep_their_own_transparency_and_empty_ones_carry_no_colour(self):
        out = server.bgra(RGBA)
        self.assertEqual(out[0:4], bytes([0, 0, 255, 255]))            # red, as B G R A
        self.assertEqual(out[4:8], bytes([0, 255, 0, 200]))            # alpha kept as drawn
        self.assertEqual(out[8:12], bytes([255, 0, 0, 60]))
        self.assertEqual(out[12:16], bytes(4))                         # fully transparent: all zero

    def test_grey_makes_every_pixel_its_own_brightness(self):
        out = server.bgra(bytes([255, 0, 0, 255, 0, 255, 0, 255]), grey=True)
        red, green = out[0:4], out[4:8]
        self.assertEqual(red[0], red[1])
        self.assertEqual(red[1], red[2])
        self.assertEqual(red[0], 76)                                    # 0.299 * 255
        self.assertEqual(green[0], 149)                                 # 0.587 * 255
        self.assertEqual((red[3], green[3]), (255, 255))

    def test_opacity_scales_the_alpha_of_every_pixel(self):
        out = server.bgra(bytes([10, 20, 30, 200, 10, 20, 30, 100, 10, 20, 30, 0]), opacity=50)
        self.assertEqual((out[3], out[7], out[11]), (100, 50, 0))
        self.assertEqual(server.bgra(bytes([1, 2, 3, 255]), opacity=1)[3], 12)       # never fully invisible: 5 % at the least

    def test_logo_meta(self):
        sizes = {'small': (96, 40), 'medium': (144, 60)}
        self.assertIsNone(logo_meta({'mode': 'off'}, 3, sizes))
        self.assertIsNone(logo_meta({'mode': 'always'}, 3, None))
        m = logo_meta({'mode': 'timed', 'seconds': 500, 'size': 'large'}, 3, sizes)      # no large one: falls back to one that exists
        self.assertEqual((m['mode'], m['seconds'], m['size'], m['file'], m['w'], m['h']), ('timed', 120, 'medium', 'logos/ch3.bgra', 144, 60))
        self.assertEqual(logo_meta({'mode': 'always', 'size': 'small'}, 3, sizes)['w'], 96)
        g = logo_meta({'mode': 'always', 'grey': True, 'opacity': 1}, 3, sizes)
        self.assertEqual((g['grey'], g['opacity']), (True, 5))             # opacity is kept between 5 and 100

    def test_compile_puts_the_logo_in_the_channel(self):
        cat = {'items': {'a': {'id': 'a', 'title': 't', 'duration': 600, 'kind': 'episode', 'show': 'S', 'season': 1, 'episode': 1, 'direct_ok': True}}}
        groups = {'g': {'item_ids': ['a']}}
        spec = {'channels': [{'number': 4, 'name': 'C', 'pools': [{'name': 'p', 'groups': ['g']}], 'dayparts': [],
                              'logo': {'mode': 'always', 'size': 'small'}}]}
        chans, _, _ = compile_all(spec, cat, groups, frozenset(), {4: {'small': (10, 5)}})
        self.assertEqual(chans[0].meta['logo']['file'], 'logos/ch4.bgra')
        chans, _, _ = compile_all(spec, cat, groups)
        self.assertNotIn('logo', chans[0].meta)


class Studio(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (server.STUDIO, server.CATALOGS, server.LOGOS, server.BUILD, server.DATA, server.DEVICE)
        server.STUDIO = self.tmp / 'studio'
        server.CATALOGS, server.LOGOS, server.BUILD = server.STUDIO / 'catalogs', server.STUDIO / 'logos', self.tmp / 'build'
        server.DATA, server.DEVICE = None, False
        os.environ.pop('JELLYFIN_API_KEY', None)
        self.state = server.State()

    def tearDown(self):
        server.STUDIO, server.CATALOGS, server.LOGOS, server.BUILD, server.DATA, server.DEVICE = self.saved

    def sizes(self, w=4, h=2):
        return {n: {'w': w, 'h': h, 'data': base64.b64encode(RGBA * 2).decode()} for n in ('small', 'medium', 'large')}

    def test_save_move_delete(self):
        self.state.logo_save(3, self.sizes())
        self.assertEqual(self.state.logo_dims(), {3: {'small': (4, 2), 'medium': (4, 2), 'large': (4, 2)}})
        self.state.logo_move(3, 9)
        self.assertEqual(list(self.state.logo_dims()), [9])
        self.assertEqual(self.state.logo_get(9)['sizes']['small']['w'], 4)
        self.state.logo_delete(9)
        self.assertEqual(self.state.logo_dims(), {})

    def test_a_wrong_sized_picture_is_refused(self):
        bad = self.sizes()
        bad['small']['w'] = 5                                        # 5x2 pixels would need more data than it carries
        with self.assertRaises(ValueError):
            self.state.logo_save(3, bad)
        huge = {'small': {'w': 999, 'h': 2, 'data': base64.b64encode(bytes(999 * 2 * 4)).decode()}}
        with self.assertRaises(ValueError):
            self.state.logo_save(3, huge)

    def test_build_writes_the_player_file(self):
        self.state.logo_save(2, self.sizes())
        cat = {'items': {'a': {'id': 'a', 'title': 't', 'duration': 600, 'kind': 'episode', 'show': 'S', 'season': 1, 'episode': 1, 'direct_ok': True}}}
        self.state.items, self.state.catalog = cat['items'], cat
        self.state.all_groups = {'g': {'item_ids': ['a']}}
        spec = {'channels': [{'number': 2, 'name': 'C', 'pools': [{'name': 'p', 'groups': ['g']}], 'dayparts': [],
                              'logo': {'mode': 'always', 'size': 'medium'}}]}
        self.state.refine_used = lambda s: 0
        self.state.build(spec)
        data = (server.BUILD / 'logos' / 'ch2.bgra').read_bytes()
        self.assertEqual(len(data), 4 * 2 * 4)
        self.assertEqual(data[:4], bytes([0, 0, 255, 255]))
        spec['channels'][0]['logo']['mode'] = 'off'                  # switched off: the old file is cleaned away
        self.state.build(spec)
        self.assertFalse((server.BUILD / 'logos' / 'ch2.bgra').exists())


class Player(unittest.TestCase):
    def folder(self, mode):
        d = tempfile.mkdtemp()
        json.dump({'items': [{'id': 'jf:1', 'title': 'T', 'duration': 1300, 'kind': 'episode', 'show': 'S', 'season': 1, 'episode': 1,
                              'direct_ok': True, 'media': ''}]}, open(os.path.join(d, 'runtime_catalog.json'), 'w'))
        lg = {'mode': mode, 'seconds': 6, 'size': 'small', 'smooth': False, 'file': 'logos/ch2.bgra', 'w': 4, 'h': 2}
        json.dump({'channels': [{'number': 2, 'name': 'C', 'slot_minutes': 30, 'anchor': '2026-01-01', 'meta': {'logo': lg},
                                 'pools': [{'name': 'p', 'item_ids': ['jf:1'], 'mode': 'shuffle'}],
                                 'dayparts': [{'start': 0, 'end': 1440, 'pools': ['p']}]}]}, open(os.path.join(d, 'channels.json'), 'w'))
        json.dump({'sources': {'jf': {'type': 'jellyfin', 'server': 'http://x', 'api_key': 'x'}}}, open(os.path.join(d, 'config.json'), 'w'))
        os.mkdir(os.path.join(d, 'logos'))
        open(os.path.join(d, 'logos', 'ch2.bgra'), 'wb').write(bytes([1, 2, 3, 255]) * 8)
        return d

    def test_logo_is_drawn_bottom_right_and_moves_above_the_banner(self):
        app = App(self.folder('always'), lambda m: None)
        self.assertTrue(app.load_data())
        got = app.logo_for(app.channels[0])
        c = Canvas()
        app.draw_logo(c, got, above_banner=False)
        x, y = 640 - 48 - 4, 480 - 40 - 2
        o = (y * 640 + x) * 4
        self.assertEqual(c.buf[o:o + 4], bytes([1, 2, 3, 255]))
        self.assertEqual(c.buf[(y * 640 + x - 1) * 4:(y * 640 + x) * 4], bytes(4))            # nothing next to it
        c.clear()
        app.draw_logo(c, got, above_banner=True)
        o = ((322 - 8 - 2) * 640 + x) * 4
        self.assertEqual(c.buf[o:o + 4], bytes([1, 2, 3, 255]))

    def test_a_missing_or_wrong_sized_file_means_no_logo(self):
        d = self.folder('always')
        app = App(d, lambda m: None)
        app.load_data()
        open(os.path.join(d, 'logos', 'ch2.bgra'), 'wb').write(b'short')
        app.logo_cache = {}
        self.assertIsNone(app.logo_for(app.channels[0]))

    def test_timed_logo_arms_for_its_seconds_and_always_does_not_need_it(self):
        app = App(self.folder('timed'), lambda m: None)
        app.load_data()
        app.arm_logo()
        self.assertGreater(app.logo_until, 0)
        app2 = App(self.folder('always'), lambda m: None)
        app2.load_data()
        app2.arm_logo()
        self.assertEqual(app2.logo_until, 0.0)


if __name__ == '__main__':
    unittest.main()
