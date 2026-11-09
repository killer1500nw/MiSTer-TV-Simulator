#!/usr/bin/env python3
"""Install MiSTer 90s TV Simulator on a MiSTer (run by Install_MiSTer_90s_TV.sh; needs only Python 3 and a network connection).

    * the program (tvsim) and its web page, into /media/fat/Scripts/.config/MiSTer_90s_TV
    * ffmpeg 7.0.2 static ARM (GPLv3, John Van Sickle's build as packaged by eugeneware/ffmpeg-static), into /media/fat/MiSTer_90s_TV,
      downloaded and checked against its pinned SHA-256
    * the H.264 core by owenb321 (github.com/owenb321/MiSTer_h264_decoder, GPL-3.0-or-later) into /media/fat/_Other if no copy is there,
      checked against its published SHA-256 (asks first)
    * the launcher and uninstaller in /media/fat/Scripts

The download and checksum code and the pinned values are adapted from the author's earlier MiSTer player (see NOTICE.md).
"""
import argparse
import gzip
import hashlib
import io
import os
import shutil
import ssl
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

FFMPEG_BASE = 'https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/'
FFMPEG_URL = FFMPEG_BASE + 'ffmpeg-linux-arm.gz'
FFMPEG_SHA256 = '64b115a12f0ab77c277e3c418aae8b40ef881e75e746a0e2d066a206b9bc5172'
FFMPEG_NOTICES = (
    ('linux-arm.LICENSE', 'GPLv3.txt', '8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903'),
    ('linux-arm.README', 'readme.txt', 'faaea83a6d92419cb112d5de5ac673f51b72401830e068c4d003b3229ee1c89a'),
)
H264_TAG = 'v1.1.0'
H264_NAME = 'H264_20261014.rbf'
H264_URL = 'https://github.com/owenb321/MiSTer_h264_decoder/releases/download/%s/%s' % (H264_TAG, H264_NAME)
H264_SHA256 = '0790a8893789092c542aabc2e1135169b57a1f29bb7663a415fe8a5a33e1bdfb'
UA = 'MiSTer-90s-TV-Simulator-setup/1.0'


def ctx():
    ca = HERE / 'cacert.pem'
    return ssl.create_default_context(cafile=str(ca)) if ca.is_file() else ssl.create_default_context()


def digest(path, algo='sha256'):
    h = hashlib.new(algo)
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, dest, label=''):
    """Download to `dest`, printing a line every ~10%. Tries three times."""
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=60, context=ctx()) as r, open(dest, 'wb') as out:
                total = int(r.headers.get('Content-Length') or 0)
                got, shown = 0, -1
                while True:
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    got += len(chunk)
                    if total and label and got * 10 // total != shown:
                        shown = got * 10 // total
                        print('  %s %d%%' % (label, shown * 10), flush=True)
            return
        except Exception as exc:                       # a network hiccup: try again
            last = exc
            print('  (%s; attempt %d of 3)' % (exc, attempt), flush=True)
            time.sleep(2 * attempt)
    raise RuntimeError('Could not download %s: %s' % (url, last))


def stop_running():
    """Stop a running copy (background starter, player and web page) so the upgrade starts clean; the starter is started again at the end.
    Only processes that are exactly `python -m tvsim.<ours>` are touched (read from /proc), never anything that merely mentions the name."""
    mine = {'tvsim.player', 'tvsim.studio', 'tvsim.daemon'}
    me = os.getpid()
    try:
        names = [n for n in os.listdir('/proc') if n.isdigit()]
    except OSError:
        return
    for name in names:
        try:
            with open('/proc/%s/cmdline' % name, 'rb') as f:
                args = f.read().split(bytes([0]))
            words = [a.decode('utf-8', 'replace') for a in args]
            if '-m' in words and words.index('-m') + 1 < len(words) and words[words.index('-m') + 1] in mine and int(name) != me:
                os.kill(int(name), 9)
        except (OSError, ValueError):
            continue
    for name in names:                                  # an older starter may have left the YouTube player held still: let it go
        try:
            with open('/proc/%s/cmdline' % name, 'rb') as f:
                text = f.read().replace(bytes([0]), b' ').decode('utf-8', 'replace')
            if 'youtube_crt.py --daemon' in text:
                os.kill(int(name), 18)                  # SIGCONT
        except (OSError, ValueError):
            continue


def install_program(app):
    print('Installing the program...')
    stop_running()
    app.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(app / 'tvsim', ignore_errors=True)
    shutil.copytree(HERE / 'tvsim', app / 'tvsim', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('VERSION.txt', 'NOTICE.md', 'cacert.pem', 'CERTIFICATES-NOTICE.txt'):
        if (HERE / name).is_file():
            shutil.copy2(HERE / name, app / name)


def install_ffmpeg(home):
    if list(home.glob('ffmpeg-*-armhf-static/ffmpeg')):
        print('ffmpeg is already installed.')
        return
    home.mkdir(parents=True, exist_ok=True)
    print('Downloading ffmpeg 7.0.2 (about 30 MB; the MiSTer writes slowly, this can take a few minutes)...', flush=True)
    gz = home / 'ffmpeg.gz.part'
    fetch(FFMPEG_URL, gz, 'ffmpeg')
    if digest(gz) != FFMPEG_SHA256:
        gz.unlink()
        raise RuntimeError('ffmpeg checksum mismatch; not installing it.')
    print('  checksum OK; unpacking...', flush=True)
    final = home / 'ffmpeg-7.0.2-armhf-static'
    stage = home / '_stage-ffmpeg'
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    try:
        with gzip.open(gz, 'rb') as src, open(stage / 'ffmpeg', 'wb') as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        for remote, local, checksum in FFMPEG_NOTICES:
            fetch(FFMPEG_BASE + remote, stage / local)
            if digest(stage / local) != checksum:
                raise RuntimeError('ffmpeg notice checksum mismatch; not installing it.')
        os.chmod(stage / 'ffmpeg', 0o755)
        shutil.rmtree(final, ignore_errors=True)
        os.rename(stage, final)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        gz.unlink()
    print('ffmpeg installed.')


def install_core(fat, assume_yes):
    other = fat / '_Other'
    if list(other.glob('H264_*.rbf')):
        print('The H.264 core is already in _Other.')
        return
    print('\nThe video is decoded by an FPGA core made by owenb321 (GPL-3.0): github.com/owenb321/MiSTer_h264_decoder')
    print('It is not part of this program. This installer can download that one file (about 4.4 MB) from the author\'s')
    print('release page, check it against the published checksum and put it in /media/fat/_Other.')
    if not assume_yes and sys.stdin.isatty():
        if input('Download the core now? [y/N] ').strip().lower() not in ('y', 'yes'):
            print('Skipped. Install the core yourself (Downloader or the link above), then start the player.')
            return
    other.mkdir(parents=True, exist_ok=True)
    part = other / (H264_NAME + '.part')
    fetch(H264_URL, part, 'H.264 core')
    if digest(part) != H264_SHA256:
        part.unlink()
        raise RuntimeError('H.264 core checksum mismatch; not installing it.')
    os.rename(part, other / H264_NAME)
    print('The H.264 core is installed.')


BEGIN, END = '# BEGIN MiSTer 90s TV Simulator', '# END MiSTer 90s TV Simulator'
STARTUP_LINE = 'case "${1:-start}" in start) ( bash /media/fat/Scripts/.config/MiSTer_90s_TV/daemon.sh </dev/null >/dev/null 2>&1 & ) ;; esac'


def install_scripts(app, scripts):
    """The background starter goes beside the program; the only script left in the Scripts menu is the uninstaller."""
    for src, target in (('MiSTer_90s_TV_daemon.sh', app / 'daemon.sh'), ('Uninstall_MiSTer_90s_TV.sh', scripts / 'Uninstall_MiSTer_90s_TV.sh')):
        target.write_bytes((HERE / src).read_bytes().replace(b'\r\n', b'\n'))
        os.chmod(target, 0o755)
    old = scripts / 'MiSTer_90s_TV.sh'                  # versions before 0.6b put a launcher in the Scripts menu
    if old.exists():
        old.unlink()


ENTRY_NAME = 'MiSTer 90s TV'


def build_date():
    """YYYYMMDD of this build: the menu shows it beside the name, as it does for every core."""
    try:
        return (HERE / 'BUILD_DATE.txt').read_text().strip()
    except OSError:
        return time.strftime('%Y%m%d')


def install_menu_entry(fat, date=None):
    """Other > MiSTer 90s TV: the MiSTer menu shows a date only for .rbf cores (name_YYYYMMDD.rbf), never for .mgl files, so the entry is a
    copy of the H.264 core under this program's name. Loading it loads the core; the background starter then starts the player."""
    other = fat / '_Other'
    cores = sorted(other.glob('H264_*.rbf'))
    if not cores:
        print('No H.264 core in _Other yet, so no menu entry was made. Install the core, then run this installer again.')
        return False
    date = date or build_date()
    target = other / ('%s_%s.rbf' % (ENTRY_NAME, date))
    for old in list(other.glob(ENTRY_NAME + '_*.rbf')) + [other / (ENTRY_NAME + '.mgl')]:      # earlier builds (and the plain .mgl of 0.6b test builds)
        if old != target and old.exists():
            old.unlink()
    shutil.copyfile(cores[-1], target)
    print('Menu entry added: Other > %s (%s)' % (ENTRY_NAME, date))
    return True


def install_startup(fat, assume_yes):
    """One line in /media/fat/linux/user-startup.sh (between marker lines, so it can be found and removed) starts the background starter at boot."""
    path = fat / 'linux' / 'user-startup.sh'
    text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else '#!/bin/sh\n'
    if BEGIN in text:
        print('The start-up line is already in user-startup.sh.')
        return True
    print('\nThe menu entry needs a small background program that starts at boot and waits for you to choose it.')
    print('This adds 3 lines (marked "MiSTer 90s TV Simulator") to %s. The uninstaller removes them.' % path)
    if not assume_yes:
        if not sys.stdin.isatty():
            print('Not added (no one to ask). Run this installer from the MiSTer menu and answer yes, or run it with -y.')
            return False
        if input('Add them now? [y/N] ').strip().lower() not in ('y', 'yes'):
            print('Skipped: Other > MiSTer 90s TV will not start the player until the background starter runs.')
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip('\n') + '\n\n%s\n%s\n%s\n' % (BEGIN, STARTUP_LINE, END), encoding='utf-8')
    return True


def start_daemon(app):
    """Start the background starter now, so the menu entry works without a reboot."""
    import subprocess
    subprocess.Popen(['bash', str(app / 'daemon.sh')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--fat', default='/media/fat', help='the MiSTer SD card (for testing elsewhere)')
    ap.add_argument('--no-download', action='store_true', help='skip the downloads (for testing the rest)')
    ap.add_argument('-y', '--yes', action='store_true', help='do not ask: download the H.264 core if missing and add the start-up line')
    a = ap.parse_args()
    fat = Path(a.fat)
    app, home, scripts = fat / 'Scripts' / '.config' / 'MiSTer_90s_TV', fat / 'MiSTer_90s_TV', fat / 'Scripts'
    scripts.mkdir(parents=True, exist_ok=True)
    problems = []
    install_program(app)
    for step in () if a.no_download else (lambda: install_ffmpeg(home), lambda: install_core(fat, a.yes)):
        try:
            step()
        except Exception as exc:
            problems.append(str(exc))
            print('PROBLEM: %s' % exc, flush=True)
    install_scripts(app, scripts)
    install_menu_entry(fat)               # (again after an update of the H.264 core, so that the entry carries the new core)
    boot = install_startup(fat, a.yes)
    start_daemon(app)
    print()
    if problems:
        print('Installed, but not everything downloaded. Run this installer again once the MiSTer is online.')
        return 1
    if boot:
        print('Done. In the MiSTer menu open Other > MiSTer 90s TV.')
    else:
        print('Installed. Without the start-up line, start the background starter by hand (bash %s/daemon.sh) or reboot after adding it.' % app)
    print('The TV shows an address and a code. Open that address in a browser on your phone or computer,')
    print('type the code, add your Jellyfin or Plex server and build your channels.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
