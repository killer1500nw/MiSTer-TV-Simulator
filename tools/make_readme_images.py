"""Draw the on-screen graphics with invented sample channels and save them as PNGs for the README (no MiSTer, no library needed).

    python tools/make_readme_images.py
"""
import datetime as dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))
from preview_overlay import png  # noqa: E402
from tvsim.player.app import App  # noqa: E402
from tvsim.player.overlay import Canvas  # noqa: E402

SHOWS = [(2, 'Captain Comet', 'Cartoons', 22), (3, 'Night Patrol', 'Crime Drama', 45), (4, 'The Fixer Uppers', 'Sitcom', 22),
         (5, 'Starbase Nine', 'Sci-Fi', 45), (6, 'Video Jukebox', 'Music', 22), (7, 'Late Night Pictures', 'Movies', 95)]


def sample_folder():
    d = tempfile.mkdtemp()
    items, chans = [], []
    for number, show, genre, mins in SHOWS:
        ids = []
        for e in range(1, 9):
            iid = 'jf:%d%02d' % (number, e)
            ids.append(iid)
            items.append({'id': iid, 'title': 'Episode %d' % e if mins < 90 else show, 'duration': mins * 60,
                          'kind': 'episode' if mins < 90 else 'movie', 'show': show if mins < 90 else '', 'season': 1, 'episode': e,
                          'direct_ok': True, 'media': ''})
        chans.append({'number': number, 'name': genre, 'slot_minutes': 30 if mins < 40 else 60, 'no_repeat_hours': 12, 'anchor': '2026-01-01',
                      'pools': [{'name': 'shows', 'item_ids': ids, 'mode': 'shuffle'}],
                      'dayparts': [{'start': 0, 'end': 1440, 'pools': ['shows']}], 'commercial_pool': None})
    json.dump({'items': items}, open(os.path.join(d, 'runtime_catalog.json'), 'w'))
    json.dump({'channels': chans}, open(os.path.join(d, 'channels.json'), 'w'))
    json.dump({'sources': {'jf': {'type': 'jellyfin', 'server': 'http://x', 'api_key': 'x'}}}, open(os.path.join(d, 'config.json'), 'w'))
    json.dump({'code': '4821'}, open(os.path.join(d, 'pairing.json'), 'w'))
    return d


def main():
    out = os.path.join(os.path.dirname(__file__), '..', 'docs', 'img')
    os.makedirs(out, exist_ok=True)
    app = App(sample_folder(), lambda m: None)
    assert app.load_data()
    app.studio_lines = lambda: ('http://192.168.1.50:8090', '4821')            # a typical home address
    now = dt.datetime.now().replace(hour=20, minute=12, second=0, microsecond=0)
    # a backdrop that looks like a picture, so the banner reads as an overlay
    back = (58, 96, 120)
    c = Canvas()
    app.idx = 1
    app.draw_banner(c, now)
    png(os.path.join(out, 'banner.png'), c, 'scene')
    c.clear()
    from tvsim.player import guide
    app.guide_sel = 2
    for name, _ in guide.THEMES:
        c.clear()
        guide.open_guide(app, now)
        app.guide_sel = 2
        guide.look(name).draw(app, c, now)
        png(os.path.join(out, 'guide-%s.png' % name), c, 'scene')
    c.clear()
    app.draw_setup(c)
    png(os.path.join(out, 'setup.png'), c)
    c.clear()
    app.tuning = 'CH 05'
    app.draw_tuning(c)
    png(os.path.join(out, 'static.png'), c)
    c.clear()
    app.aspect_msg = 'ZOOM 16:9: Cut 16:9 bars baked in, fill'
    app.draw_aspect(c)
    png(os.path.join(out, 'shape.png'), c, 'scene')
    print('wrote', out)


main()
