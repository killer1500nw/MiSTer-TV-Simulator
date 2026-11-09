import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.player import app as appmod
from tests.test_guide import make_app


class T(unittest.TestCase):
    def test_leaving_never_unloads_a_core_that_is_not_ours(self):
        log = []
        with mock.patch.object(appmod.hr, 'core_name', return_value='MisterZine Plex Core'), \
                mock.patch.object(appmod.os, 'open', side_effect=AssertionError('must not write to the command pipe')):
            appmod.leave_to_menu(log.append)
        self.assertTrue(any('not touching' in m for m in log))

    def test_leaving_still_works_from_our_core(self):
        with mock.patch.object(appmod.hr, 'core_name', return_value='H264'), \
                mock.patch.object(appmod.os, 'open', side_effect=OSError('no pipe here')) as op:
            log = []
            appmod.leave_to_menu(log.append)
        self.assertTrue(op.called)
        self.assertTrue(any('Could not return' in m for m in log))

    def test_another_core_loaded_over_ours_is_noticed(self):
        app = make_app()
        for name, expect in (('H264', False), ('MENU', False), ('', False), ('MisterZine Plex Core', True), ('YouTube', True)):
            with mock.patch.object(appmod.hr, 'core_name', return_value=name):
                self.assertEqual(app.core_taken_over(False), expect, name)

    def test_the_same_core_loaded_by_another_programs_entry_is_noticed(self):
        app = make_app()
        from tvsim import daemon
        mine = [(1, ['/media/fat/MiSTer', '/media/fat/_Other/MiSTer 90s TV_20261102.rbf'])]
        other = [(1, ['/media/fat/MiSTer', '/media/fat/_Other/YouTube H264_20261014.rbf'])]
        with mock.patch.object(appmod.hr, 'core_name', return_value='H264'), mock.patch.dict(os.environ, {'C90_GUARD': '1'}):
            with mock.patch.object(daemon, 'processes', return_value=mine):
                self.assertFalse(app.core_taken_over(True))
            with mock.patch.object(daemon, 'processes', return_value=other):
                self.assertTrue(app.core_taken_over(True))

    def test_a_player_that_lost_the_core_writes_nothing_on_the_way_out(self):
        app = make_app()
        app.foreign = True
        calls = []
        app.ov = mock.Mock(close=lambda: calls.append('ov'))
        app.ring = mock.Mock(close=lambda: calls.append('ring'), release=lambda: calls.append('release'))
        app.mem = mock.Mock(close=lambda: calls.append('mem'))
        app.close_core()
        self.assertEqual(calls, ['mem'])


    def test_the_holder_of_the_decoder_lock_is_found_in_proc_locks(self):
        from tvsim.player import h264ring
        text = ('1: POSIX  ADVISORY  WRITE 812 00:1f:777 0 EOF' + chr(10) +
                '2: FLOCK  ADVISORY  WRITE 1379 00:1f:12345 0 EOF' + chr(10))
        self.assertEqual(h264ring.lock_holder_pid(text, 12345), 1379)
        self.assertEqual(h264ring.lock_holder_pid(text, 999), 0)
        self.assertEqual(h264ring.lock_holder_pid('', 1), 0)


if __name__ == '__main__':
    unittest.main()
