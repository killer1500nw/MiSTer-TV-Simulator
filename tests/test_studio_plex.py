import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.studio import server


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (server.STUDIO, server.CATALOGS, server.DATA, server.DEVICE)
        server.STUDIO, server.CATALOGS, server.DATA, server.DEVICE = self.tmp / 'studio', self.tmp / 'studio' / 'catalogs', None, False
        self.pins = {'tok': None}
        server.plexlib.pin_start = lambda: {'id': 77, 'code': 'ABCD', 'url': 'https://app.plex.tv/auth#?code=ABCD'}
        server.plexlib.pin_check = lambda pin_id: self.pins['tok'] if pin_id == 77 else None
        server.plexlib.servers = lambda token: [{'name': 'Home', 'connections': [{'uri': 'http://192.168.1.5:32400', 'local': True}]}]
        os.environ.pop('JELLYFIN_API_KEY', None)
        self.state = server.State()

    def tearDown(self):
        server.STUDIO, server.CATALOGS, server.DATA, server.DEVICE = self.saved

    def test_nothing_pending(self):
        self.assertEqual(self.state.plex_pin_check()['state'], 'none')

    def test_sign_in_survives_the_page_being_gone(self):
        self.state.plex_pin_start()
        self.assertEqual(self.state.plex_pin_check()['state'], 'pending')
        self.pins['tok'] = 'SECRET-TOKEN'                       # the user approves in the other tab; no page is open
        fresh = server.State()                                  # even a restarted Studio carries on
        r = fresh.plex_pin_check()
        self.assertEqual(r['state'], 'signed_in')
        src = fresh.source(r['id'])
        self.assertEqual((src['type'], src['token'], src['server']), ('plex', 'SECRET-TOKEN', ''))
        self.assertEqual(fresh.plex_pin_check()['state'], 'none')            # one pin, one sign-in
        # the browser sees only that a credential exists
        self.assertTrue(next(s for s in fresh.overview()['sources'] if s['id'] == r['id'])['has_credential'])
        self.assertNotIn('SECRET-TOKEN', json.dumps(fresh.overview()))

    def test_signing_in_again_reuses_the_unsigned_source(self):
        self.state.plex_pin_start()
        self.pins['tok'] = 'T1'
        first = self.state.plex_pin_check()['id']
        self.assertEqual(len([s for s in self.state.sources() if s['type'] == 'plex']), 1)
        self.assertEqual(first, 'plex')

    def test_servers_use_the_saved_token(self):
        self.state.plex_pin_start()
        self.pins['tok'] = 'T1'
        sid = self.state.plex_pin_check()['id']
        self.assertEqual(self.state.plex_servers(sid)[0]['name'], 'Home')

    def test_expired_pin(self):
        self.state.plex_pin_start()
        (server.STUDIO / 'plex_pin.json').write_text(json.dumps({'id': 77, 'at': time.time() - 2000}))
        self.assertEqual(self.state.plex_pin_check()['state'], 'expired')
        self.assertEqual(self.state.plex_pin_check()['state'], 'none')

    def test_unchecked_items_are_checked_when_a_channel_uses_them(self):
        from tvsim import plexindex
        item = lambda i, unchecked: {'id': 'plex:%d' % i, 'title': 't%d' % i, 'duration': 1300, 'kind': 'episode', 'show': 'S', 'season': 1,
                                     'episode': i, 'direct_ok': not unchecked, 'why': 'interlaced' if unchecked else 'ok', 'media': '/p/%d' % i,
                                     'unchecked': unchecked, 'video': {}}
        cat = {'items': {'plex:1': item(1, True), 'plex:2': item(2, True), 'plex:3': item(3, False)},
               'groups': [{'id': 'plex:g', 'type': 'series', 'name': 'S', 'source': 'plex', 'item_ids': ['plex:1', 'plex:2', 'plex:3']}]}
        server.write_json(server.STUDIO / 'config.json', {'sources': [{'id': 'plex', 'type': 'plex', 'name': 'P', 'server': 'http://x', 'token': 'T'}]})
        server.write_json(server.CATALOGS / 'plex.json', cat)
        self.state.reload()
        asked = []

        def fake_refine(client, rec):
            asked.append(rec['id'])
            rec.update(direct_ok=True, why='ok', unchecked=False)
            return rec
        self.addCleanup(setattr, plexindex, 'refine', plexindex.refine)
        plexindex.refine = fake_refine
        self.state.client = lambda src: object()
        spec = {'channels': [{'number': 5, 'name': 'C', 'pools': [{'name': 'a', 'items': ['plex:1', 'plex:3']}], 'dayparts': []}]}
        self.state.build(spec)
        self.assertEqual(asked, ['plex:1'])                       # only what the channel uses, and only the unchecked one
        saved = json.loads((server.CATALOGS / 'plex.json').read_text(encoding='utf-8'))['items']
        self.assertTrue(saved['plex:1']['direct_ok'] and not saved['plex:1']['unchecked'])
        self.assertTrue(saved['plex:2']['unchecked'])             # unused: left for later


if __name__ == '__main__':
    unittest.main()
