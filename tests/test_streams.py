import os
import sys
import unittest
import urllib.parse as up

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim import streams
from tvsim.model import Item

CFG = streams.normalize({'sources': {
    'jf': {'type': 'jellyfin', 'server': 'http://j:8096', 'api_key': 'K'},
    'plex': {'type': 'plex', 'server': 'http://p:32400', 'token': 'T'}}})


class T(unittest.TestCase):
    def test_old_config_means_source_jf(self):
        cfg = streams.normalize({'server': 'http://x', 'api_key': 'k'})
        self.assertEqual(cfg['sources']['jf']['server'], 'http://x')

    def test_jellyfin(self):
        st = streams.stream(CFG, Item('jf:abc', 't', 60), 30, 's')
        self.assertEqual(st.video_url, st.audio_url)
        self.assertIn('/Videos/abc/stream?', st.video_url)
        self.assertEqual(st.seek_s, 30.0)
        self.assertTrue(st.audio_seekable)

    def test_plex_direct_uses_the_part(self):
        st = streams.stream(CFG, Item('plex:77', 't', 60, media='/library/parts/9/1/file.mkv'), 30, 's')
        self.assertTrue(st.video_url.startswith('http://p:32400/library/parts/9/1/file.mkv?X-Plex-Token=T'))
        self.assertEqual(st.seek_s, 30.0)
        self.assertIsNone(st.prepare)

    def test_plex_transcode_is_one_hls_session_with_a_decision_first(self):
        st = streams.stream(CFG, Item('plex:77', 't', 60, direct_ok=False), 125.7, 'sess')
        q = dict(up.parse_qsl(up.urlparse(st.video_url).query))
        self.assertIn('/video/:/transcode/universal/start.m3u8?', st.video_url)
        self.assertEqual((q['path'], q['offset'], q['directPlay'], q['directStream'], q['protocol']),
                         ('/library/metadata/77', '125', '0', '0', 'hls'))
        self.assertEqual(q['X-Plex-Platform'], 'Chrome')                  # Plex only knows client profiles by platform
        self.assertEqual(st.video_url, st.audio_url)                      # one session serves the picture and the sound
        self.assertIsNotNone(st.prepare)                                  # the decision request
        self.assertFalse(st.audio_seekable)
        self.assertEqual(st.seek_s, 0.0)

    def test_unknown_source(self):
        with self.assertRaises(RuntimeError):
            streams.stream(CFG, Item('zzz:1', 't', 60), 0, 's')


if __name__ == '__main__':
    unittest.main()
