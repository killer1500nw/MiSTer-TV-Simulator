import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location('install_setup', os.path.join(HERE, '..', 'tools', 'installer', 'install_setup.py'))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def card(core=True, entry=True, startup=True, ffmpeg=True):
    fat = Path(tempfile.mkdtemp())
    (fat / '_Other').mkdir()
    (fat / 'linux').mkdir()
    if core:
        (fat / '_Other' / 'H264_20261014.rbf').write_bytes(b'x')
    if entry:
        (fat / '_Other' / 'MiSTer 90s TV_20261109.rbf').write_bytes(b'x')
    (fat / 'linux' / 'user-startup.sh').write_text('#!/bin/sh\n' + (setup.BEGIN + '\nx\n' + setup.END + '\n' if startup else ''))
    if ffmpeg:
        (fat / 'MiSTer_90s_TV' / 'ffmpeg-7.0.2-armhf-static').mkdir(parents=True)
        (fat / 'MiSTer_90s_TV' / 'ffmpeg-7.0.2-armhf-static' / 'ffmpeg').write_bytes(b'x')
    return fat


def check(fat, programs):
    out = io.StringIO()
    with mock.patch.object(setup, 'running_programs', lambda: programs), mock.patch('time.sleep', lambda s: None), redirect_stdout(out):
        bad = setup.self_check(fat, fat / 'Scripts')
    return bad, out.getvalue()


class SelfCheck(unittest.TestCase):
    RUNNING = ['python3 -u -m tvsim.daemon', '/usr/bin/python3 -u -m tvsim.studio']

    def test_all_in_place(self):
        bad, text = check(card(), self.RUNNING)
        self.assertEqual(bad, 0)
        self.assertNotIn('[!!]', text)

    def test_a_missing_core_is_called_out_with_what_to_do(self):
        bad, text = check(card(core=False, entry=False), self.RUNNING)
        self.assertEqual(bad, 2)
        self.assertIn("[!!] H.264 core in _Other: MISSING. Install owenb321's core", text)
        self.assertIn('[!!] menu entry: MISSING', text)
        self.assertIn('MiSTer_90s_TV_Diagnose', text)                        # and where to go if it does not clear up

    def test_the_other_gaps(self):
        bad, text = check(card(startup=False, ffmpeg=False), [])
        self.assertEqual(bad, 4)
        self.assertIn('[!!] start-up line in user-startup.sh: MISSING', text)
        self.assertIn('[!!] ffmpeg: MISSING', text)
        self.assertIn('[!!] background starter: NOT running', text)

    def test_what_the_installer_prints_is_kept_for_install_log(self):
        tee = setup.Tee(io.StringIO())
        tee.write('hello ')
        tee.write('world')
        self.assertEqual(''.join(tee.lines), 'hello world')
        self.assertEqual(tee.real.getvalue(), 'hello world')


if __name__ == '__main__':
    unittest.main()
