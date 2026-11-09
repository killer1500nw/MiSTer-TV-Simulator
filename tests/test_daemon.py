import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
from tvsim import daemon

spec = importlib.util.spec_from_file_location('install_setup', os.path.join(HERE, '..', 'tools', 'installer', 'install_setup.py'))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class Daemon(unittest.TestCase):
    def test_only_our_menu_entry_counts(self):
        ours = [(7, ['/media/fat/MiSTer', '/media/fat/_Other/H264_20261014.rbf', '/media/fat/_Other/MiSTer 90s TV.mgl'])]
        rbf = [(7, ['/media/fat/MiSTer', '/media/fat/_Other/MiSTer 90s TV_20261102.rbf'])]
        rbf_underscores = [(7, ['/media/fat/MiSTer', '/media/fat/_Other/MiSTer_90s_TV_20261102.rbf'])]
        theirs = [(7, ['/media/fat/MiSTer', '/media/fat/_Other/H264_20261014.rbf', '/media/fat/_Other/YouTube (H264).mgl'])]
        script = [(7, ['/media/fat/MiSTer', '/media/fat/_Other/H264_20261014.rbf', '/tmp/h264ring.mgl'])]
        menu = [(7, ['/media/fat/MiSTer', '/media/fat/menu.rbf'])]
        self.assertTrue(daemon.loaded_by_our_entry(ours))
        self.assertTrue(daemon.loaded_by_our_entry(rbf))
        self.assertTrue(daemon.loaded_by_our_entry(rbf_underscores))
        for other in (theirs, script, menu):
            self.assertFalse(daemon.loaded_by_our_entry(other))

    def test_a_matching_file_name_elsewhere_is_not_the_menu_program(self):
        self.assertFalse(daemon.loaded_by_our_entry([(9, ['python3', 'x', 'MiSTer 90s TV.mgl'])]))

    def test_running_ignores_itself(self):
        me = [(os.getpid(), ['python3', '-m', 'tvsim.daemon']), (5, ['python3', '-m', 'tvsim.studio'])]
        self.assertFalse(daemon.running(me, 'tvsim.daemon'))
        self.assertTrue(daemon.running(me, 'tvsim.studio'))


    def test_the_youtube_player_is_found_by_its_command_line_and_held_then_released(self):
        from unittest import mock
        procs = [(10, ['python3', '/media/fat/Scripts/.config/YouTubeCRT/youtube_crt.py', '--daemon']), (11, ['python3', '-m', 'tvsim.studio']),
                 (os.getpid(), ['python3', 'youtube_crt.py', '--daemon'])]
        self.assertEqual(daemon.feeder_pids(procs), [10])
        self.assertNotIn(os.getpid(), daemon.feeder_pids(procs))
        sent = []
        with mock.patch.object(daemon.os, 'kill', lambda pid, sig: sent.append((pid, sig))):
            daemon.signal_all([10, 12], 19)
            daemon.signal_all([10, 12], 18)
        self.assertEqual(sent, [(10, 19), (12, 19), (10, 18), (12, 18)])


    def test_a_stopped_youtube_player_is_started_again_through_its_own_launcher(self):
        d = tempfile.mkdtemp()
        script = os.path.join(d, 'youtube_crt.py')
        launcher = os.path.join(d, 'youtube_crt_daemon.sh')
        Path(launcher).write_text('#!/bin/bash' + chr(10))
        self.assertEqual(daemon.restart_command(['python3', script, '--daemon']), ['bash', launcher])
        os.unlink(launcher)
        self.assertEqual(daemon.restart_command(['python3', script, '--daemon']), ['python3', script, '--daemon'])


class Installer(unittest.TestCase):
    def setUp(self):
        self.fat = Path(tempfile.mkdtemp())
        (self.fat / 'linux').mkdir()
        self.file = self.fat / 'linux' / 'user-startup.sh'
        self.original = '#!/bin/sh\n# something else\necho hello\n'
        self.file.write_text(self.original)

    def test_nothing_is_added_when_nobody_agreed(self):
        stdin, sys.stdin = sys.stdin, None
        try:
            class NoTty:
                def isatty(self):
                    return False
            sys.stdin = NoTty()
            self.assertFalse(setup.install_startup(self.fat, assume_yes=False))
        finally:
            sys.stdin = stdin
        self.assertEqual(self.file.read_text(), self.original)

    def test_yes_adds_the_marked_block_once_and_keeps_the_rest(self):
        self.assertTrue(setup.install_startup(self.fat, assume_yes=True))
        self.assertTrue(setup.install_startup(self.fat, assume_yes=True))
        text = self.file.read_text()
        self.assertTrue(text.startswith(self.original.rstrip('\n')))
        self.assertEqual(text.count(setup.BEGIN), 1)
        self.assertEqual(text.count('daemon.sh'), 1)
        self.assertEqual(text.count(setup.END), 1)

    def test_the_menu_entry_is_a_dated_copy_of_the_core(self):
        other = self.fat / '_Other'
        other.mkdir()
        (other / 'H264_20261014.rbf').write_bytes(b'core bytes')
        (other / 'MiSTer 90s TV_20260101.rbf').write_bytes(b'older entry')
        (other / 'MiSTer 90s TV.mgl').write_text('old test entry')
        self.assertTrue(setup.install_menu_entry(self.fat, '20261102'))
        self.assertEqual((other / 'MiSTer 90s TV_20261102.rbf').read_bytes(), b'core bytes')       # the menu shows "MiSTer 90s TV" and the date
        self.assertEqual(sorted(p.name for p in other.iterdir()), ['H264_20261014.rbf', 'MiSTer 90s TV_20261102.rbf'])

    def test_without_the_core_no_entry_is_made(self):
        self.assertFalse(setup.install_menu_entry(self.fat, '20261102'))
        self.assertFalse((self.fat / '_Other' / 'MiSTer 90s TV_20261102.rbf').exists())

    def test_the_uninstaller_removes_exactly_the_block(self):
        import re
        setup.install_startup(self.fat, assume_yes=True)
        text = self.file.read_text()
        removed = re.sub(r'# BEGIN MiSTer 90s TV Simulator.*?# END MiSTer 90s TV Simulator\n?', '', text, flags=re.S)
        self.assertEqual(removed.strip(), self.original.strip())
        uninstall = (Path(HERE) / '..' / 'tools' / 'installer' / 'Uninstall_MiSTer_90s_TV.sh').read_text()
        self.assertIn("/# BEGIN MiSTer 90s TV Simulator/,/# END MiSTer 90s TV Simulator/d", uninstall)


if __name__ == '__main__':
    unittest.main()
