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
    """Stop a running copy (player and web page) so the upgrade starts clean; the launcher starts both again."""
    import subprocess
    try:
        out = subprocess.run(['ps'], capture_output=True, text=True).stdout
    except OSError:
        return
    for line in out.splitlines():
        if ('tvsim.player' in line or 'tvsim.studio' in line) and 'grep' not in line:
            try:
                os.kill(int(line.split()[0]), 9)
            except (ValueError, OSError):
                pass


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


def install_scripts(scripts):
    for name in ('MiSTer_90s_TV.sh', 'Uninstall_MiSTer_90s_TV.sh'):
        data = (HERE / name).read_bytes().replace(b'\r\n', b'\n')
        target = scripts / name
        target.write_bytes(data)
        os.chmod(target, 0o755)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--fat', default='/media/fat', help='the MiSTer SD card (for testing elsewhere)')
    ap.add_argument('--no-download', action='store_true', help='skip the downloads (for testing the rest)')
    ap.add_argument('-y', '--yes', action='store_true', help='do not ask before downloading the H.264 core')
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
    install_scripts(scripts)
    print()
    if problems:
        print('Installed, but not everything downloaded. Run this installer again once the MiSTer is online.')
        return 1
    print('Done. In the MiSTer menu open Scripts > MiSTer_90s_TV.')
    print('The TV shows an address and a code. Open that address in a browser on your phone or computer,')
    print('type the code, add your Jellyfin or Plex server and build your channels.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
