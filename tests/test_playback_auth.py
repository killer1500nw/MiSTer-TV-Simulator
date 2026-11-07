import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tvsim.model import Item
from tvsim.player.app import App


TOKEN = 'fake-jellyfin-playback-token'
HEADER = 'Authorization: MediaBrowser Token="%s"\r\n' % TOKEN


class PlaybackAuthTest(unittest.TestCase):
    def setUp(self):
        self.app = App('.', lambda msg: None)
        self.app.rt = SimpleNamespace(ffmpeg='ffmpeg', ca='/unused/ca.pem')
        self.app.aspects = SimpleNamespace(steps=lambda item: None)
        self.app.ring = MagicMock()
        self.app.cfg = {'sources': {
            'jf': {'type': 'jellyfin', 'server': 'http://j:8096', 'api_key': TOKEN},
            'plex': {'type': 'plex', 'server': 'http://p:32400', 'token': 'fake-plex-token'},
        }}

    def assert_jellyfin_command(self, cmd, direct, video):
        self.assertEqual(cmd[cmd.index('-headers') + 1], HEADER)
        self.assertLess(cmd.index('-headers'), cmd.index('-i'))
        url = cmd[cmd.index('-i') + 1]
        self.assertNotIn(TOKEN, url)
        self.assertNotIn('api_key', parse_qs(urlsplit(url).query))
        self.assertEqual(urlsplit(url).path, '/Videos/abc/stream' if direct else '/Videos/abc/stream.ts')
        if direct:
            self.assertEqual(parse_qs(urlsplit(url).query), {'Static': ['true']})
        else:
            self.assertEqual(parse_qs(urlsplit(url).query)['StartTimeTicks'], ['300000000'])
        if video:
            self.assertIn('-c:v', cmd)
        else:
            self.assertIn('-c:a', cmd)
            self.assertEqual(cmd[cmd.index('-seek_timestamp') + 1], '1')

    def test_clip_commands_for_direct_and_transcode(self):
        for direct in (True, False):
            with self.subTest(direct=direct):
                entry = self.app.clip(Item('jf:abc', 'title', 60, direct_ok=direct), 30, 'session')
                self.assertEqual(entry.seek_s, 30.0 if direct else 0.0)
                self.assertFalse(entry.audio_early)
                video = entry.video_cmd(entry.seek_s)
                audio = entry.audio_cmd(1.4)
                self.assert_jellyfin_command(video, direct, video=True)
                self.assert_jellyfin_command(audio, direct, video=False)
                if direct:
                    self.assertEqual(video[video.index('-ss') + 1], '30.000')
                else:
                    self.assertNotIn('-ss', video)
                self.assertEqual(audio[audio.index('-ss') + 1], '1.400')
                # Reopened streams must use the same authorization as the first request.
                self.assert_jellyfin_command(entry.video_cmd(2.0), direct, video=True)
                self.assert_jellyfin_command(entry.audio_cmd(2.0), direct, video=False)

    def test_play_modes_use_clip_commands_for_both_streams(self):
        item = Item('jf:abc', 'title', 60)
        airing = SimpleNamespace(item=item, end=86400)
        ch = SimpleNamespace(number=1)
        self.app.sched = SimpleNamespace(day=lambda ch, date: [airing])
        self.app.programme_key = lambda ch: 'slot'

        for chain in (True, False):
            for direct in (True, False):
                with self.subTest(chain=chain, direct=direct):
                    item.direct_ok = direct
                    self.app.cfg['chain'] = chain
                    feeder = MagicMock(first_pts=None, stats={})
                    feeder.take_lead.return_value = None
                    with patch('tvsim.player.app.ChainFeeder', return_value=feeder) as chain_cls, \
                         patch('tvsim.player.app.h264feed.Feeder', return_value=feeder) as feeder_cls:
                        self.app.play(ch, airing, 30)
                    if chain:
                        entry = chain_cls.call_args.args[1][0]
                        vcmd, acmd, seek = entry.video_cmd, entry.audio_cmd, entry.seek_s
                        feeder.start.assert_called_once_with(0.0)
                        feeder_cls.assert_not_called()
                    else:
                        args = feeder_cls.call_args.args
                        vcmd, acmd = args[1:3]
                        seek = 30.0 if direct else 0.0
                        feeder.start.assert_called_once_with(seek)
                        chain_cls.assert_not_called()
                    self.assertEqual(seek, 30.0 if direct else 0.0)
                    self.assert_jellyfin_command(vcmd(seek), direct, video=True)
                    self.assert_jellyfin_command(acmd(1.4), direct, video=False)

    def test_plex_commands_keep_existing_behavior(self):
        for direct in (True, False):
            with self.subTest(direct=direct):
                item = Item('plex:77', 'title', 60, direct_ok=direct, media='/library/parts/9/file.mkv')
                entry = self.app.clip(item, 30, 'session')
                with patch('tvsim.plexurl.urllib.request.urlopen') as urlopen:
                    video = entry.video_cmd(entry.seek_s)
                    audio = entry.audio_cmd(1.4)
                self.assertNotIn('-headers', video)
                self.assertNotIn('-headers', audio)
                self.assertEqual(video[video.index('-i') + 1], audio[audio.index('-i') + 1])
                if direct:
                    self.assertEqual(entry.seek_s, 30.0)
                    self.assertFalse(entry.audio_early)
                    self.assertEqual(video[video.index('-ss') + 1], '30.000')
                    self.assertEqual(audio[audio.index('-ss') + 1], '1.400')
                    urlopen.assert_not_called()
                else:
                    self.assertEqual(entry.seek_s, 0.0)
                    self.assertTrue(entry.audio_early)
                    self.assertNotIn('-ss', video)
                    self.assertNotIn('-ss', audio)
                    urlopen.assert_called_once()


if __name__ == '__main__':
    unittest.main()
