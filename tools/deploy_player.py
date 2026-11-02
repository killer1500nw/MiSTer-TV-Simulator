"""Copy the player to the MiSTer over SSH and start it. When it exits (BACK twice) the MiSTer menu comes back.

    set JELLYFIN_API_KEY=...
    python tools/deploy_player.py --server http://localhost:8096            # copy + run
    python tools/deploy_player.py --log                                                # show the player's log
    python tools/deploy_player.py --stop                                               # stop it and return to the MiSTer menu

The MiSTer's address is in tools/mister_host.txt (or --host); SSH uses ~/.ssh/mister_ed25519.
Only one program can feed the H.264 core, so any other player of that core that starts at boot is stopped (not restarted).
"""
import argparse
import io
import json
import os
import socket
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = Path.home() / '.ssh' / 'mister_ed25519'
HOST_FILE = ROOT / 'tools' / 'mister_host.txt'
DIR = '/media/fat/Scripts/.config/MiSTer_90s_TV'
HOME = '/media/fat/MiSTer_90s_TV'
MENU = 'echo "load_core /media/fat/menu.rbf" > /dev/MiSTer_cmd'
# our player and its wrapper, plus other programs that feed the H.264 core, then any ffmpeg they left behind
STOP = ('for p in $(ps | grep -v grep | grep -E "tvsim.player|youtube_crt.py --daemon|h264play" | awk \'{print $1}\'); '
        'do kill -9 $p; done; for p in $(ps | grep -v grep | grep "ffmpeg-.*-armhf-static" | awk \'{print $1}\'); do kill -9 $p; done; sleep 1')


def ssh_exe():
    """Git for Windows' ssh when present: Windows' own OpenSSH refuses a key that other accounts on the PC can read."""
    git = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git' / 'usr' / 'bin' / 'ssh.exe'
    return str(git) if git.exists() else 'ssh'


def ssh(host, remote, **kw):
    """Run a command on the MiSTer. A busy MiSTer sometimes lets an SSH connection time out (exit 255): try again a few times."""
    for attempt in range(4):
        r = subprocess.run([ssh_exe(), '-i', str(KEY), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'root@' + host, remote], **kw)
        if r.returncode != 255:
            return r
        print('(no answer from the MiSTer, trying again)')
        time.sleep(3)
    return r


def add(tar, name, data, mode=0o644):
    info = tarfile.TarInfo(name)
    info.size, info.mode = len(data), mode
    tar.addfile(info, io.BytesIO(data))


def load_sources(fallback_server):
    """{source id: {type, server, credential}} from Studio's saved sources (or the old environment variable)."""
    path = ROOT / 'studio' / 'config.json'
    out = {}
    if path.exists():
        for s in json.loads(path.read_text(encoding='utf-8')).get('sources', []):
            keep = {k: s[k] for k in ('type', 'server', 'api_key', 'token', 'transcode') if k in s}
            if keep.get('server') and (keep.get('api_key') or keep.get('token')):
                out[s['id']] = keep
    key = os.environ.get('JELLYFIN_API_KEY', '').strip()
    if not out and key:
        out['jf'] = {'type': 'jellyfin', 'server': fallback_server, 'api_key': key}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--server', default='http://localhost:8096')
    ap.add_argument('--host')
    ap.add_argument('--build', default=str(ROOT / 'build'))
    ap.add_argument('--log', action='store_true')
    ap.add_argument('--stop', action='store_true')
    a = ap.parse_args()
    host = a.host or HOST_FILE.read_text().strip()
    if a.log:
        ssh(host, 'tail -n 80 %s/log.txt' % DIR)
        return
    if a.stop:
        ssh(host, STOP + '; ' + MENU)
        return
    sources = load_sources(a.server)
    if not sources:
        sys.exit('No sources: add a Jellyfin or Plex server in Studio (or set JELLYFIN_API_KEY).')
    lan = None
    for sid, src in sources.items():
        if '//localhost' in src['server'] or '//127.0.0.1' in src['server']:        # the MiSTer needs this PC's LAN address
            if lan is None:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.connect((host, 22))
                lan = sock.getsockname()[0]
            src['server'] = src['server'].replace('localhost', lan).replace('127.0.0.1', lan)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for f in sorted((ROOT / 'tvsim').rglob('*.py')):
            add(tar, f.relative_to(ROOT).as_posix(), f.read_bytes())
        for name in ('channels.json', 'runtime_catalog.json', 'guide_theme.txt'):
            if not (Path(a.build) / name).exists():
                continue
            add(tar, name, (Path(a.build) / name).read_bytes())
        add(tar, 'config.json', json.dumps({'chain': True, 'sources': sources}).encode())
    r = ssh(host, 'mkdir -p %s && rm -rf %s/tvsim && tar x -C %s' % (DIR, DIR, DIR), input=buf.getvalue())
    if r.returncode:
        sys.exit('copy failed')
    # ffmpeg (a static ARM build, GPLv3, kept in third_party/) lives in the player's own folder on the card; sent once
    r = ssh(host, 'ls %s/ffmpeg-*-armhf-static/ffmpeg' % HOME, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode:
        src = next((ROOT / 'third_party').glob('ffmpeg-*-armhf-static'), None)
        if src is None:
            sys.exit('No ffmpeg on the MiSTer and none in third_party/ to send.')
        print('Sending %s (about 30 MB; SD writes are slow, this takes a minute or two)...' % src.name)
        pack = io.BytesIO()
        with tarfile.open(fileobj=pack, mode='w') as tar:
            for f in sorted(src.iterdir()):
                add(tar, '%s/%s' % (src.name, f.name), f.read_bytes(), 0o755 if f.name == 'ffmpeg' else 0o644)
        r = ssh(host, 'mkdir -p %s && tar x -C %s' % (HOME, HOME), input=pack.getvalue())
        if r.returncode:
            sys.exit('ffmpeg copy failed')
    inner = 'cd %s && python3 -u -m tvsim.player %s </dev/null >/tmp/c90.out 2>&1' % (DIR, DIR)
    ssh(host, '%s; cd %s && : > log.txt; nohup sh -c "%s" </dev/null >/dev/null 2>&1 &' % (STOP, DIR, inner))
    print('Started on %s. Press BACK twice to exit to the MiSTer menu; log: python tools/deploy_player.py --log' % host)


main()
