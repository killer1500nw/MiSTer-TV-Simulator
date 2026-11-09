"""Starts the MiSTer 90s TV player when "Other > MiSTer 90s TV" is chosen in the MiSTer menu.

The menu entry is a .mgl file that loads the H.264 core; this program (started at boot from /media/fat/linux/user-startup.sh) watches for
that and starts the player, which then draws on the loaded core. It acts only when the core was loaded by *our* menu entry (the entry's
file name is on the MiSTer program's command line), so other programs that use the same core are left alone. It also keeps Studio (the
web page) running, at low priority, so the address on the TV works the moment the player starts.
"""
import atexit
import os
import signal
import subprocess
import sys
import time

FOLDER = os.environ.get('C90_DATA') or '/media/fat/Scripts/.config/MiSTer_90s_TV'
ENTRY_MARK = '90s tv'                 # in the file name of our menu entry: "MiSTer 90s TV_20261102.rbf" (or the older "MiSTer 90s TV.mgl")
OTHER_FEEDERS = ('youtube_crt.py --daemon',)      # a program that would grab the core as well: stopped while ours runs, then started again
POLL = 1.0


def log(msg):
    print('%s %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg), flush=True)


def processes():
    """[(pid, [arguments])] of everything running (from /proc: no ps parsing)."""
    out = []
    for name in os.listdir('/proc'):
        if name.isdigit():
            try:
                with open('/proc/%s/cmdline' % name, 'rb') as f:
                    args = [a.decode('utf-8', 'replace') for a in f.read().split(b'\0') if a]
            except OSError:
                continue
            if args:
                out.append((int(name), args))
    return out


def core_name():
    try:
        with open('/tmp/CORENAME') as f:
            return f.read().strip()
    except OSError:
        return ''


def loaded_by_our_entry(procs):
    """Was the running core loaded from our menu entry? (the MiSTer program is started with the entry's path)"""
    for _, args in procs:
        if args[0].endswith('/MiSTer') and any(ENTRY_MARK in a.lower().replace('_', ' ') for a in args[1:]):
            return True
    return False


def feeder_pids(procs):
    return [pid for pid, args in procs if pid != os.getpid() and any(o in ' '.join(args) for o in OTHER_FEEDERS)]


def restart_command(args):
    """How to start a stopped feeder again: its own launcher script when it has one (it sets up the log), else the same command line."""
    for a in args:
        if a.endswith('youtube_crt.py'):
            launcher = os.path.join(os.path.dirname(a), 'youtube_crt_daemon.sh')
            if os.path.isfile(launcher):
                return ['bash', launcher]
    return list(args)


def signal_all(pids, sig):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def ours(procs):
    return loaded_by_our_entry(procs)


def running(procs, text):
    return any(text in ' '.join(args) for pid, args in procs if pid != os.getpid())


def start_studio():
    logfile = os.path.join(FOLDER, 'studio.log')
    try:
        if os.path.getsize(logfile) > 1000000:
            open(logfile, 'w').close()
    except OSError:
        pass
    env = dict(os.environ, C90_DATA=FOLDER)
    out = open(logfile, 'a')
    subprocess.Popen(['nice', '-n', '19', sys.executable, '-u', '-m', 'tvsim.studio'], cwd=FOLDER, env=env, stdout=out, stderr=out,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    log('started Studio')


def main():
    if running(processes(), 'tvsim.daemon'):
        return 0                                           # one is enough
    log('watching for Other > MiSTer 90s TV (folder %s)' % FOLDER)
    player, started, quick, last_studio = None, 0.0, 0, 0.0
    stopped = []                                                         # commands of the other players of the core stopped while ours runs

    def let_go():
        """Start the other players again (they hold the decoder's lock while they run, so they have to be stopped, not just paused)."""
        if not stopped:
            return
        for cmd in stopped:
            if not feeder_pids(processes()):                          # (not when something has already started one)
                try:
                    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                    log('started the other player of the core again')
                except OSError as exc:
                    log('could not start it again: %s' % exc)
        del stopped[:]

    atexit.register(let_go)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))                # (so the exit hook above runs)
    while True:
        try:
            now = time.time()
            name = core_name()                                           # (one tiny file read: the process list is only read when needed)
            if now - last_studio > 15.0:
                last_studio = now
                if not running(processes(), 'tvsim.studio'):
                    start_studio()
            if stopped and (name != 'H264' or (int(now) % 3 == 0 and not ours(processes()))):
                let_go()                                                 # the menu (or another program's entry) is back: the other player may work again
            if player is not None and player.poll() is None and name not in ('H264', 'MENU', ''):
                try:
                    player.kill()                                      # another core (Plex, YouTube...) was loaded: leave it alone
                    log('stopped our player: the core is now %r' % name)
                except OSError:
                    pass
            if player is not None and player.poll() is not None:
                quick = quick + 1 if now - started < 20 else 0           # a player that dies at once is not restarted forever
                log('the player ended (exit %s)' % player.returncode)
                player = None
            if name != 'H264':
                quick = 0                                                # the menu is back: the next choice gets a fresh start
            elif player is None and quick < 4 and now - started > 5.0 and ours(processes()):
                for pid, args in processes():                             # one program at a time can feed the core: stop the other (it is started again later)
                    if pid in feeder_pids([(pid, args)]):
                        stopped.append(restart_command(args))
                        signal_all([pid], signal.SIGKILL)
                        log('stopped another player of the core (pid %d); it starts again when we are done' % pid)
                if stopped:
                    time.sleep(0.5)                                       # (so its lock on the decoder is gone)
                out = open('/tmp/c90.out', 'a')
                player = subprocess.Popen([sys.executable, '-u', '-m', 'tvsim.player', FOLDER], cwd=FOLDER, stdout=out, stderr=out,
                                          env=dict(os.environ, C90_GUARD='1'),
                                          stdin=subprocess.DEVNULL, start_new_session=True)
                started = now
                log('started the player')
        except Exception as exc:                                         # never let the watcher die
            log('error: %s' % exc)
        time.sleep(POLL)


if __name__ == '__main__':
    sys.exit(main())
