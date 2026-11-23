import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim import daemon, diagnose

TOKEN = 'abcdef0123456789SECRETKEY'
PLEX = 'PLEXtoken_9876543210abc'


class Report(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / 'studio').mkdir()
        (self.d / 'VERSION.txt').write_text('9.9.9b\n')
        (self.d / 'studio' / 'config.json').write_text(json.dumps({'sources': [
            {'id': 'jf', 'type': 'jellyfin', 'server': 'http://192.168.1.5:8096', 'api_key': TOKEN},
            {'id': 'plex', 'type': 'plex', 'server': 'http://192.168.1.5:32400', 'token': PLEX}]}))
        (self.d / 'channels.json').write_text(json.dumps({'channels': [{'number': 2, 'name': 'Cartoons'}]}))
        (self.d / 'log.txt').write_text('12:00:00 ch 2: x\n12:00:01 ffmpeg said: https://s/x?api_key=%s&y=1\n12:00:02 header Token="%s"\n' % (TOKEN, TOKEN))
        (self.d / 'studio.log').write_text('Studio: http://0.0.0.0:8090 (Ctrl-C to stop)  code 5669\n')
        (self.d / 'pairing.json').write_text('{"code": "5669"}')
        self.text = diagnose.report(str(self.d))

    def test_the_report_names_the_version_and_the_setup(self):
        self.assertIn('MiSTer 90s TV Simulator 9.9.9b', self.text)
        self.assertIn('jf jellyfin http://192.168.1.5:8096 (signed in)', self.text)
        self.assertIn('plex plex http://192.168.1.5:32400 (signed in)', self.text)
        self.assertIn('channels: 1 (2 Cartoons)', self.text)
        self.assertIn('ch 2: x', self.text)                                  # the log tail is there

    def test_no_secret_is_in_the_report(self):
        for secret in (TOKEN, PLEX, '5669'):
            self.assertNotIn(secret, self.text)
        self.assertIn('api_key=***', self.text)
        self.assertIn('code ****', self.text)

    def test_missing_files_do_not_break_it(self):
        text = diagnose.report(str(self.d / 'nothing-here'))
        self.assertIn('diagnostics', text)
        self.assertIn('MISSING', text)

    def test_redact(self):
        self.assertEqual(diagnose.redact('X-Plex-Token=abcdef1234567890&a=1'), 'X-Plex-Token=***&a=1')
        self.assertEqual(diagnose.redact('{"api_key": "abcdefghijkl"}'), '{"api_key": "***"}')
        self.assertEqual(diagnose.redact('exit code 3'), 'exit code 3')


class Explain(unittest.TestCase):
    OURS = [(7, ['/media/fat/MiSTer', '/media/fat/_Other/MiSTer 90s TV_20261109.rbf'])]
    PLAIN = [(7, ['/media/fat/MiSTer', '/media/fat/_Other/H264_20261014.rbf'])]

    def test_our_entry_with_the_expected_core_may_start(self):
        self.assertEqual(daemon.explain('H264', self.OURS), (True, ''))

    def test_the_plain_core_is_explained(self):
        ok, why = daemon.explain('H264', self.PLAIN)
        self.assertFalse(ok)
        self.assertIn('not from Other > MiSTer 90s TV', why)
        self.assertIn('H264_20261014.rbf', why)                              # the file the MiSTer program was started with

    def test_a_different_core_name_is_explained(self):
        ok, why = daemon.explain('H264Dec', self.OURS)
        self.assertFalse(ok)
        self.assertIn("'H264Dec'", why)
        self.assertIn('not "H264"', why)

    def test_the_menu_and_other_cores(self):
        self.assertEqual(daemon.explain('MENU', [(7, ['/media/fat/MiSTer', '/media/fat/menu.rbf'])]), (False, ''))
        ok, why = daemon.explain('PlexClient', [(7, ['/media/fat/MiSTer', '/media/fat/_Other/Zine.rbf'])])
        self.assertFalse(ok)
        self.assertIn('another core', why)

    def test_the_program_not_found(self):
        ok, why = daemon.explain('H264', [])
        self.assertFalse(ok)
        self.assertIn('was not found', why)


if __name__ == '__main__':
    unittest.main()
