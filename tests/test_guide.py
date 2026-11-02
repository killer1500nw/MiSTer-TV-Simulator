import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.player import guide
from tvsim.player.app import App
from tvsim.player.overlay import Canvas
from tvsim.studio import server


def make_app(theme_file=None, cfg_theme=None):
    d = tempfile.mkdtemp()
    items, chans = [], []
    for number, mins in ((2, 22), (3, 45), (4, 95)):
        ids = []
        for e in range(1, 6):
            iid = 'jf:%d%d' % (number, e)
            ids.append(iid)
            items.append({'id': iid, 'title': 'Episode %d' % e, 'duration': mins * 60, 'kind': 'episode' if mins < 90 else 'movie',
                          'show': 'Show %d' % number, 'season': 1, 'episode': e, 'direct_ok': True, 'media': '', 'year': 1994, 'rating': 'TV-PG',
                          'overview': 'A long description of the programme. ' * 12})
        chans.append({'number': number, 'name': 'Chan %d' % number, 'slot_minutes': 30 if mins < 40 else 60, 'anchor': '2026-01-01',
                      'pools': [{'name': 'p', 'item_ids': ids, 'mode': 'shuffle'}], 'dayparts': [{'start': 0, 'end': 1440, 'pools': ['p']}]})
    Path(d, 'runtime_catalog.json').write_text(json.dumps({'items': items}))
    Path(d, 'channels.json').write_text(json.dumps({'channels': chans}))
    cfg = {'sources': {'jf': {'type': 'jellyfin', 'server': 'http://x', 'api_key': 'x'}}}
    if cfg_theme:
        cfg['guide_theme'] = cfg_theme
    Path(d, 'config.json').write_text(json.dumps(cfg))
    if theme_file:
        Path(d, 'guide_theme.txt').write_text(theme_file)
    app = App(d, lambda m: None)
    assert app.load_data()
    app.studio_lines = lambda: ('http://192.168.1.50:8090', '4821')
    return app


class T(unittest.TestCase):
    def test_cells_tile_the_whole_day_for_every_channel(self):
        app = make_app()
        day = dt.date(2026, 11, 2)
        for ch in app.channels:
            cells = guide.day_cells(app, ch, day)
            self.assertEqual(cells[0].start, dt.datetime(2026, 11, 2))
            self.assertEqual(cells[-1].end, dt.datetime(2026, 11, 3))
            for a, b in zip(cells, cells[1:]):
                self.assertEqual(a.end, b.start)

    def test_left_and_right_move_one_programme_and_the_window_follows(self):
        app = make_app()
        now = dt.datetime.now().replace(hour=12, minute=10, second=0, microsecond=0)
        guide.open_guide(app, now)
        ch = app.channels[app.guide_sel]
        here = guide.cell_at(app, ch, app.guide_at)
        guide.move(app, 'right', 8, 3)
        after = guide.cell_at(app, ch, app.guide_at)
        self.assertEqual(after.start, here.end)
        self.assertLess(app.guide_win, after.start + dt.timedelta(seconds=1))
        for _ in range(6):
            guide.move(app, 'right', 8, 3)
        self.assertGreaterEqual(app.guide_at, app.guide_win)
        self.assertLess(app.guide_at, app.guide_win + dt.timedelta(minutes=90))        # the cursor stays inside the window
        guide.move(app, 'left', 8, 3)
        self.assertLess(app.guide_at, after.start + dt.timedelta(hours=9))

    def test_up_down_wrap_and_pages_stop_at_the_ends(self):
        app = make_app()
        guide.open_guide(app, dt.datetime.now())
        app.guide_sel = 0
        guide.move(app, 'up', 3, 3)
        self.assertEqual(app.guide_sel, len(app.channels) - 1)
        guide.move(app, 'pgdn', 3, 3)
        self.assertEqual(app.guide_sel, len(app.channels) - 1)
        guide.move(app, 'pgup', 3, 3)
        self.assertEqual(app.guide_sel, 0)

    def test_every_look_draws_something_and_stays_inside_the_canvas(self):
        for name, _ in guide.THEMES:
            app = make_app()
            guide.open_guide(app, dt.datetime.now())
            c = Canvas()
            guide.look(name).draw(app, c, dt.datetime.now())
            self.assertGreater(sum(1 for a in c.buf[3::4] if a), 20000, name)           # a real picture, not a blank page
            self.assertEqual(len(c.buf), 640 * 480 * 4)

    def test_the_picture_shows_through_cable_and_modern(self):
        for name in ('cable', 'modern'):
            app = make_app()
            guide.open_guide(app, dt.datetime.now())
            c = Canvas()
            guide.look(name).draw(app, c, dt.datetime.now())
            self.assertEqual(c.buf[3::4][20 * 640 + 600], 0, name)                       # the top right (cable) / top (modern) is clear

    def test_themes_cycle_and_unknown_names_fall_back(self):
        names = [k for k, _ in guide.THEMES]
        seen, t = [], names[0]
        for _ in names:
            seen.append(t)
            t = guide.next_theme(t)
        self.assertEqual(sorted(seen), sorted(names))
        self.assertEqual(t, names[0])
        self.assertEqual(guide.next_theme('nonsense'), guide.DEFAULT_THEME)
        self.assertIs(guide.look('nonsense'), guide.look(guide.DEFAULT_THEME))

    def test_the_chosen_look_is_the_file_then_the_config_then_the_default(self):
        self.assertEqual(make_app().read_theme(), guide.DEFAULT_THEME)
        self.assertEqual(make_app(cfg_theme='modern').read_theme(), 'modern')
        self.assertEqual(make_app(theme_file='cable', cfg_theme='modern').read_theme(), 'cable')
        self.assertEqual(make_app(theme_file='garbage', cfg_theme='modern').read_theme(), 'modern')

    def test_pressing_y_in_the_guide_changes_and_remembers_the_look(self):
        app = make_app(theme_file='satellite')
        app.guide_open = True
        app.theme = 'satellite'
        app.handle('menu')
        self.assertEqual(app.theme, 'cable')
        self.assertEqual(Path(app.folder, 'guide_theme.txt').read_text(), 'cable')

    def test_y_shows_the_details_and_moving_hides_them(self):
        app = make_app()
        app.guide_open = True
        app.theme = 'cable'
        guide.open_guide(app, dt.datetime.now())
        app.handle('info')
        self.assertTrue(app.guide_info)
        c = Canvas()
        guide.draw_info(app, c, dt.datetime.now())
        self.assertGreater(sum(1 for a in c.buf[3::4] if a), 100000)
        app.handle('back')
        self.assertTrue(app.guide_open and not app.guide_info)
        app.handle('info')
        app.handle('down')
        self.assertFalse(app.guide_info)
        self.assertEqual(app.theme, 'cable')

    def test_names_wrap_between_words_never_inside_one(self):
        self.assertEqual(guide.wrap_words('3 SATURDAY TOONS', 10), ['3 SATURDAY', 'TOONS'])
        self.assertIsNone(guide.wrap_words('SATURDAY TOONS', 6))


class Studio(unittest.TestCase):
    def test_studio_only_accepts_known_looks(self):
        tmp = Path(tempfile.mkdtemp())
        saved = server.BUILD
        server.BUILD = tmp
        try:
            state = server.State.__new__(server.State)                                # the look needs no catalogs
            self.assertEqual(state.theme(), guide.DEFAULT_THEME)
            state.set_theme('modern')
            self.assertEqual(state.theme(), 'modern')
            with self.assertRaises(ValueError):
                state.set_theme('../../etc/passwd')
            self.assertEqual((tmp / 'guide_theme.txt').read_text(), 'modern')
        finally:
            server.BUILD = saved


if __name__ == '__main__':
    unittest.main()
