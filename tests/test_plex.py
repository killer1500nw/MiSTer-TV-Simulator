import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim import plexindex
from tvsim.plex import Plex


def media(codec='h264', profile='high', w=640, h=480, rate='24p', br=1500, parts=1, key='/library/parts/1/1/f.mkv'):
    return {'videoCodec': codec, 'videoProfile': profile, 'width': w, 'height': h, 'videoFrameRate': rate, 'bitrate': br,
            'Part': [{'key': key + str(i)} for i in range(parts)]}


MOVIE = {'ratingKey': '10', 'type': 'movie', 'title': 'A Movie', 'duration': 5400000, 'year': 1995, 'Media': [media()]}
EPS = [
    {'ratingKey': '21', 'type': 'episode', 'title': 'Pilot', 'duration': 1320000, 'grandparentTitle': 'Toon Show', 'grandparentRatingKey': '20',
     'parentIndex': 1, 'index': 1, 'Media': [media()]},
    {'ratingKey': '22', 'type': 'episode', 'title': 'Second', 'duration': 1320000, 'grandparentTitle': 'Toon Show', 'grandparentRatingKey': '20',
     'parentIndex': 1, 'index': 2, 'Media': [media(codec='hevc', profile='main 10', w=1920, h=1080)]},
    {'ratingKey': '23', 'type': 'episode', 'title': 'Old DVD', 'duration': 1320000, 'grandparentTitle': 'Toon Show', 'grandparentRatingKey': '20',
     'parentIndex': 2, 'index': 1, 'Media': [media(rate='NTSC')]},
    {'ratingKey': '24', 'type': 'episode', 'title': 'Split', 'duration': 1320000, 'grandparentTitle': 'Toon Show', 'grandparentRatingKey': '20',
     'parentIndex': 2, 'index': 2, 'Media': [media(parts=2)]},
    {'ratingKey': '25', 'type': 'episode', 'title': 'No media', 'duration': 1320000, 'grandparentTitle': 'Toon Show',
     'grandparentRatingKey': '20', 'parentIndex': 2, 'index': 3},
]


def container(rows, key='Metadata', start=0, size=200):
    page = rows[start:start + size]
    return {'MediaContainer': {'size': len(page), 'totalSize': len(rows), key: page}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        assert self.headers.get('X-Plex-Token') == 'TOK'
        start, size = int(q.get('X-Plex-Container-Start', 0)), int(q.get('X-Plex-Container-Size', 200))
        p = u.path
        if p == '/library/sections':
            body = container([{'key': '1', 'type': 'movie', 'title': 'Movies'}, {'key': '2', 'type': 'show', 'title': 'TV'},
                              {'key': '3', 'type': 'artist', 'title': 'Music'}], 'Directory')
        elif p == '/library/sections/1/all':
            body = container([MOVIE], start=start, size=size)
        elif p == '/library/sections/2/all':
            assert q['type'] == '4'
            body = container(EPS, start=start, size=size)
        elif p == '/playlists':
            body = container([{'ratingKey': '90', 'title': 'Night Mix'}])
        elif p == '/playlists/90/items':
            body = container([MOVIE, EPS[0]])
        elif p == '/library/sections/1/collections':
            body = container([{'ratingKey': '95', 'title': 'Nineties'}])
        elif p == '/library/sections/2/collections':
            body = container([{'ratingKey': '96', 'title': 'Toons'}])
        elif p == '/library/collections/95/children':
            body = container([MOVIE])
        elif p == '/library/collections/96/children':
            body = container([{'ratingKey': '20', 'type': 'show', 'title': 'Toon Show'}])
        elif p.startswith('/library/metadata/'):
            scan = 'interlaced' if p.endswith('/23') else 'progressive'
            body = {'MediaContainer': {'Metadata': [{'Media': [{'Part': [{'Stream': [
                {'streamType': 2, 'codec': 'aac'},
                {'streamType': 1, 'codec': 'h264', 'profile': 'main', 'bitDepth': 8, 'chromaSubsampling': '4:2:0', 'scanType': scan,
                 'width': 640, 'height': 480, 'frameRate': '29.97', 'bitrate': 1500}]}]}]}]}}
        else:
            body = container([])
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = 'http://127.0.0.1:%d' % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_ntsc_that_is_really_progressive_plays_direct(self):
        meta = dict(EPS[2], ratingKey='99')                                               # same NTSC listing, progressive stream
        self.assertEqual(plexindex.item_record(meta, 'px')['why'], 'interlaced')          # the listing alone guesses interlaced
        rec = plexindex.refine(Plex(self.url, 'TOK'), plexindex.item_record(meta, 'px'))
        self.assertTrue(rec['direct_ok'], rec['why'])
        self.assertFalse(rec['unchecked'])

    def test_rates(self):
        self.assertEqual(plexindex.parse_rate('24p'), (24.0, False))
        self.assertEqual(plexindex.parse_rate('NTSC'), (29.97, True))
        self.assertEqual(plexindex.parse_rate('1080i'), (1080.0, True))
        self.assertEqual(plexindex.parse_rate(None), (0.0, False))

    def test_catalog(self):
        cat = plexindex.build(Plex(self.url, 'TOK'), log=lambda m: None, slug='px')
        it = cat['items']
        self.assertEqual(sorted(it), ['px:10', 'px:21', 'px:22', 'px:23', 'px:24'])      # 25 has no media
        self.assertTrue(it['px:10']['direct_ok'])
        self.assertEqual(it['px:21']['media'], '/library/parts/1/1/f.mkv0')
        self.assertEqual(it['px:22']['why'], 'codec hevc')
        self.assertEqual(it['px:23']['why'], 'interlaced')                                # NTSC: guessed at listing time ...
        self.assertTrue(it['px:23']['unchecked'])                                         # ... and marked to be checked when a channel uses it
        self.assertFalse(it['px:21']['unchecked'])
        self.assertEqual(it['px:24']['why'], 'file in several parts')
        self.assertEqual(it['px:21']['show'], 'Toon Show')
        g = {x['id']: x for x in cat['groups']}
        self.assertEqual(g['px:lib1']['item_ids'], ['px:10'])
        self.assertEqual(len(g['px:lib2']['item_ids']), 4)
        self.assertEqual(g['px:20']['type'], 'series')
        self.assertEqual(g['px:90']['item_ids'], ['px:10', 'px:21'])
        self.assertEqual(g['px:95']['item_ids'], ['px:10'])
        self.assertEqual(len(g['px:96']['item_ids']), 4)                                  # collection of a show = its episodes
        self.assertTrue(all(x['source'] == 'px' for x in cat['groups']))
        self.assertNotIn('TOK', json.dumps(cat))


if __name__ == '__main__':
    unittest.main()
