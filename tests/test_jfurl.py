import os
import sys
import unittest
import urllib.parse as up

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim import jfurl
from tvsim.model import Item

CFG = {'server': 'http://h:8096/jf/', 'api_key': 'fake-jellyfin-token'}
HEADERS = {'Authorization': 'MediaBrowser Token="fake-jellyfin-token"'}


class T(unittest.TestCase):
    def test_direct(self):
        url, seek, headers = jfurl.stream(CFG, Item('jf:abc', 't', 60, direct_ok=True), 30, 's')
        self.assertEqual(up.urlsplit(url).path, '/jf/Videos/abc/stream')
        self.assertEqual(up.parse_qs(up.urlsplit(url).query), {'Static': ['true']})
        self.assertNotIn(CFG['api_key'], url)
        self.assertEqual(headers, HEADERS)
        self.assertEqual(seek, 30.0)

    def test_transcode_always_reencodes_and_starts_on_server(self):
        url, seek, headers = jfurl.stream(CFG, Item('jf:abc', 't', 60, direct_ok=False), 30.5, 's')
        q = up.parse_qs(up.urlsplit(url).query)
        self.assertEqual(up.urlsplit(url).path, '/jf/Videos/abc/stream.ts')
        self.assertEqual(q['AllowVideoStreamCopy'], ['false'])  # re-encode, not just re-wrap Baseline H.264
        self.assertEqual(q['StartTimeTicks'], ['305000000'])
        self.assertEqual(q['PlaySessionId'], ['s'])
        self.assertNotIn('api_key', q)
        self.assertNotIn(CFG['api_key'], url)
        self.assertEqual(headers, HEADERS)
        self.assertEqual(seek, 0.0)

    def test_transcode_at_zero_and_custom_settings(self):
        cfg = dict(CFG, transcode={'MaxWidth': 640, 'api_key': CFG['api_key'], 'ApiKey': CFG['api_key'],
                                   'X-Emby-Token': CFG['api_key']})
        url, seek, headers = jfurl.stream(cfg, Item('jf:abc', 't', 60, direct_ok=False), 0, 'session')
        q = up.parse_qs(up.urlsplit(url).query)
        self.assertEqual(q['MaxWidth'], ['640'])
        self.assertNotIn('StartTimeTicks', q)
        self.assertNotIn('api_key', q)
        self.assertNotIn('ApiKey', q)
        self.assertNotIn('X-Emby-Token', q)
        self.assertNotIn(CFG['api_key'], url)
        self.assertEqual(headers, HEADERS)
        self.assertEqual(seek, 0.0)


if __name__ == '__main__':
    unittest.main()
