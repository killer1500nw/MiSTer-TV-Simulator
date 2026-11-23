import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.player import app as appmod
from tests.test_guide import make_app

ENTRY = '/media/fat/_Other/MiSTer 90s TV_20261122.rbf'


def runnable_app():
    """An App whose run() can be driven without a MiSTer: the core, the overlay and the pad are mocked away."""
    app = make_app()
    app.open_core = mock.Mock()
    app.static_frame = mock.Mock()
    app.close_core = mock.Mock()
    app.recover_core = mock.Mock()
    from tvsim.schedule import Airing
    item = app.items['jf:21']
    app.sched.now = lambda ch, now: (Airing(0, 86400, item, 0), 0)         # a programme is on, whatever the time of day
    app.pad = mock.Mock(poll=lambda: [])
    app.load_data = mock.Mock(return_value=True)                           # (run() would build a new schedule over ours)
    return app


def run(app, play):
    app.play = play
    logs = []
    app.log = logs.append
    with mock.patch.object(appmod, 'Runtime', mock.Mock()), mock.patch.object(appmod.rumble, 'Mute', mock.Mock()):
        app.run()
    return logs


class LeftOurCore(unittest.TestCase):
    def test_the_menu_another_core_or_another_entry_means_we_left(self):
        app = make_app()
        for name, expect in (('MENU', True), ('', True), ('MisterZine Plex Core', True)):
            with mock.patch.object(appmod.hr, 'core_name', return_value=name):
                self.assertEqual(app.left_our_core(), expect, name)
        with mock.patch.object(appmod.hr, 'core_name', return_value='H264'), mock.patch.object(app, 'core_taken_over', return_value=False):
            self.assertFalse(app.left_our_core())
        with mock.patch.object(appmod.hr, 'core_name', return_value='H264'), mock.patch.object(app, 'core_taken_over', return_value=True):
            self.assertTrue(app.left_our_core())


class NoRecoveryAfterLeaving(unittest.TestCase):
    def test_a_core_error_after_the_user_went_to_the_menu_reloads_nothing(self):
        app = runnable_app()
        calls = []

        def play(*a):
            calls.append('play')
            raise appmod.hr.RingError('The core did not start a session.')
        with mock.patch.object(app, 'left_our_core', return_value=True), mock.patch.object(appmod.hr, 'core_name', return_value='MENU'):
            logs = run(app, play)
        app.recover_core.assert_not_called()                           # (this reloaded the plain core and brought up the YouTube player)
        self.assertTrue(app.foreign)
        self.assertEqual(calls, ['play'])
        self.assertTrue(any('left our core' in m and 'without touching' in m for m in logs))

    def test_a_wedged_core_that_is_still_ours_is_still_recovered(self):
        app = runnable_app()
        calls = []

        def play(*a):
            calls.append('play')
            if len(calls) == 1:
                raise appmod.hr.RingError('The core is writing its status all the time.')
            app.quit = True                                            # the second try works; end the run
        with mock.patch.object(app, 'left_our_core', return_value=False):
            run(app, play)
        app.recover_core.assert_called_once()
        self.assertFalse(app.foreign)


class ReloadThroughOurEntry(unittest.TestCase):
    def open(self, app, env, entry):
        ring = mock.Mock()
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(appmod, 'our_entry', return_value=entry), \
                mock.patch.object(appmod, 'send_command') as send, \
                mock.patch.object(appmod.hr, 'launch_core') as launch, \
                mock.patch.object(appmod.hr, 'core_name', return_value='H264'), \
                mock.patch.object(appmod.hr, 'open_devmem', return_value=(ring, mock.Mock())), \
                mock.patch.object(appmod, 'Overlay'), mock.patch.object(appmod, 'Pad'):
            app.open_core(reload=True)
        return send, launch

    def test_the_starter_launched_player_reloads_through_our_menu_entry(self):
        send, launch = self.open(make_app(), {'C90_GUARD': '1'}, ENTRY)
        send.assert_called_once_with('load_core ' + ENTRY)
        launch.assert_not_called()                                      # the plain core would look like another program's to the starter

    def test_without_the_starter_or_an_entry_the_plain_core_is_loaded(self):
        for env, entry in (({}, ENTRY), ({'C90_GUARD': '1'}, None)):
            app = make_app()
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop('C90_GUARD', None)
                send, launch = self.open(app, env, entry)
            send.assert_not_called()
            launch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
