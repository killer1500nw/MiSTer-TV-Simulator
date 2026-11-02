import base64
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim import share
from tests.test_guide import make_app


def folder(channels='{"channels": []}', logos=()):
    d = Path(tempfile.mkdtemp())
    (d / 'channels.json').write_text(channels)
    (d / 'runtime_catalog.json').write_text('{"items": []}')
    (d / 'config.json').write_text('{"sources": {}}')
    (d / 'pairing.json').write_text('{"code": "1234"}')
    for n in logos:
        (d / 'logos').mkdir(exist_ok=True)
        (d / 'logos' / ('ch%d.bgra' % n)).write_bytes(b'\x01\x02\x03\x04' * 4)
    return d


def serve(data, code='4821'):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.headers.get('X-Studio-Code') != code:
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps({'stamp': share.stamp(str(data))} if self.path.endswith('/stamp') else share.pack(str(data))).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class T(unittest.TestCase):
    def test_a_copy_has_the_same_files_and_the_same_stamp(self):
        a, b = folder('{"channels": [1]}', logos=(2, 3)), folder()
        share.unpack(share.pack(str(a)), str(b))
        self.assertEqual(share.stamp(str(a)), share.stamp(str(b)))
        self.assertEqual(sorted(os.listdir(b / 'logos')), ['ch2.bgra', 'ch3.bgra'])
        self.assertEqual((b / 'pairing.json').read_text(), '{"code": "1234"}')                    # the copy never touches the pairing code

    def test_logos_that_are_gone_are_removed_on_the_copy(self):
        a, b = folder(logos=(2,)), folder(logos=(2, 9))
        share.unpack(share.pack(str(a)), str(b))
        self.assertEqual(os.listdir(b / 'logos'), ['ch2.bgra'])

    def test_unexpected_names_and_damaged_copies_are_refused(self):
        a, b = folder(), folder()
        bundle = share.pack(str(a))
        evil = dict(bundle, files=dict(bundle['files'], **{'../x.py': base64.b64encode(b'x').decode()}))
        with self.assertRaises(ValueError):
            share.unpack(evil, str(b))
        bad = dict(bundle, stamp='0' * 40)
        with self.assertRaises(ValueError):
            share.unpack(bad, str(b))
        self.assertFalse((Path(b).parent / 'x.py').exists())

    def test_joining_needs_the_right_code_and_then_follows_changes(self):
        main, mine = folder('{"channels": [{"n": 1}]}'), folder()
        srv = serve(main)
        port = srv.server_address[1]
        with self.assertRaises(share.ShareError) as cm:
            share.join(str(mine), '127.0.0.1', port, '0000')
        self.assertIn('code', str(cm.exception))
        share.join(str(mine), '127.0.0.1', port, '4821', 'Lounge', 'abc')
        self.assertEqual((mine / 'channels.json').read_text(), '{"channels": [{"n": 1}]}')
        self.assertEqual(share.following(str(mine))['name'], 'Lounge')
        self.assertFalse(share.check(str(mine)))                                                  # nothing changed: nothing copied
        (main / 'channels.json').write_text('{"channels": [{"n": 2}]}')
        self.assertTrue(share.check(str(mine)))
        self.assertEqual((mine / 'channels.json').read_text(), '{"channels": [{"n": 2}]}')
        share.leave(str(mine))
        self.assertIsNone(share.following(str(mine)))
        srv.shutdown()

    def test_a_mister_without_channels_cannot_be_joined(self):
        main, mine = folder(), folder()
        (main / 'runtime_catalog.json').unlink()
        srv = serve(main)
        with self.assertRaises(share.ShareError):
            share.join(str(mine), '127.0.0.1', srv.server_address[1], '4821')
        srv.shutdown()

    def test_discovery_finds_a_listener_and_skips_ourselves(self):
        data = folder()
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()
        share.UDP_PORT, saved = port, share.UDP_PORT
        try:
            share.serve_discovery(str(data), 8090)
            time.sleep(0.3)
            found = share.scan('someone else', 1.0, '127.0.0.1', port)
            self.assertEqual([m['name'] for m in found], ['MiSTer'])
            self.assertEqual(found[0]['port'], 8090)
            self.assertEqual(share.scan(share.device(str(data))['id'], 0.6, '127.0.0.1', port), [])
        finally:
            share.UDP_PORT = saved

    def test_the_tv_join_screen_takes_the_code_by_pad(self):
        app = make_app()
        app.setup = True
        sent = []
        app.send_join = lambda: sent.append(list(app.join['code']))
        app.join = {'stage': 'list', 'found': [{'name': 'Lounge', 'host': '10.0.0.5', 'port': 8090, 'id': 'x'}], 'sel': 0, 'code': [0] * 4,
                    'pos': 0, 'msg': ''}
        app.handle('ok')
        self.assertEqual(app.join['stage'], 'code')
        for a in ('up', 'up', 'ok', 'digit:7', 'down', 'right', 'ok'):
            app.handle(a)
        self.assertEqual(sent, [[2, 7, 9, 0]])
        app.handle('back')
        self.assertIsNone(app.join)


if __name__ == '__main__':
    unittest.main()
