"""Share one MiSTer's channels with others on the same network.

A channel's schedule follows from its channel file and the clock, so two MiSTers with the same files show the same programme at the same
moment. "Joining" a MiSTer therefore only copies its files: channels, the items they use, the server sign-ins and the logos. A joined
MiSTer then asks the other, about every five minutes, whether anything changed (one small request) and copies again only when it did.

Finding each other: a MiSTer answers a single UDP broadcast on port 8091 with its name, and does nothing else on the network until asked.
Copying needs the other MiSTer's four-digit code, the same one its web page asks for.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request

UDP_PORT = 8091
MAGIC = b'mister-90s-tv?'
SHARED = ('channels.json', 'runtime_catalog.json', 'config.json')            # channels.json is written last: the player reloads on it
LOGO = re.compile(r'^logos/ch\d{1,3}\.bgra$')
POLL_SECONDS = 300


def read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_atomic(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


# this MiSTer's name and id ---------------------------------------------------------------------------------------------------------
def device(data):
    """-> {'id', 'name'} kept in <data>/device.json (made on first use)."""
    path = os.path.join(data, 'device.json')
    d = read_json(path, {})
    if not (isinstance(d.get('id'), str) and d['id']):
        d = {'id': secrets.token_hex(6), 'name': d.get('name') or 'MiSTer'}
        write_atomic(path, json.dumps(d).encode('utf-8'))
    return {'id': d['id'], 'name': str(d.get('name') or 'MiSTer')[:24]}


def set_name(data, name):
    d = device(data)
    d['name'] = (name or '').strip()[:24] or 'MiSTer'
    write_atomic(os.path.join(data, 'device.json'), json.dumps(d).encode('utf-8'))
    return d


# what is shared ---------------------------------------------------------------------------------------------------------------------
def collect(data):
    """-> {file name: bytes} for every shared file that exists."""
    out = {}
    for name in SHARED:
        try:
            with open(os.path.join(data, name), 'rb') as f:
                out[name] = f.read()
        except OSError:
            pass
    folder = os.path.join(data, 'logos')
    if os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            name = 'logos/' + f
            if LOGO.match(name):
                with open(os.path.join(folder, f), 'rb') as fh:
                    out[name] = fh.read()
    return out


def stamp_of(files):
    h = hashlib.sha1()
    for name in sorted(files):
        h.update(name.encode('utf-8') + b'\0' + hashlib.sha1(files[name]).digest())
    return h.hexdigest()


def stamp(data):
    return stamp_of(collect(data))


def pack(data):
    files = collect(data)
    return {'stamp': stamp_of(files), 'files': {k: base64.b64encode(v).decode('ascii') for k, v in files.items()}}


def unpack(bundle, data):
    """Write a bundle from another MiSTer into `data`. Raises ValueError when it is not one we accept."""
    files = {}
    for name, text in (bundle.get('files') or {}).items():
        if name not in SHARED and not LOGO.match(name):
            raise ValueError('unexpected file %r' % name)
        files[name] = base64.b64decode(text)
    if 'channels.json' not in files or 'runtime_catalog.json' not in files:
        raise ValueError('the other MiSTer has no channels yet')
    if stamp_of(files) != bundle.get('stamp'):
        raise ValueError('the copy was damaged on the way')
    json.loads(files['channels.json'].decode('utf-8'))
    for name in sorted(files, key=lambda n: n == 'channels.json'):                  # channels.json last
        write_atomic(os.path.join(data, name), files[name])
    folder = os.path.join(data, 'logos')
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            if 'logos/' + f not in files and LOGO.match('logos/' + f):
                os.unlink(os.path.join(folder, f))
    return len(files)


# finding other MiSTers -----------------------------------------------------------------------------------------------------------
def serve_discovery(data, http_port, log=print):
    """Answer "who is there?" broadcasts with this MiSTer's name. Runs in a background thread and is silent otherwise."""
    def run():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', UDP_PORT))
        except OSError as exc:
            log('sharing: cannot listen on UDP %d: %s' % (UDP_PORT, exc))
            return
        while True:
            try:
                msg, addr = sock.recvfrom(256)
                if msg == MAGIC:
                    d = device(data)
                    reply = {'app': 'mister-90s-tv', 'id': d['id'], 'name': d['name'], 'port': http_port}
                    sock.sendto(json.dumps(reply).encode('utf-8'), addr)
            except OSError:
                time.sleep(1)
    threading.Thread(target=run, name='share-discovery', daemon=True).start()


def scan(own_id='', wait=1.5, target='255.255.255.255', port=UDP_PORT):
    """-> [{'id', 'name', 'host', 'port'}] of the other MiSTers that answered a broadcast within `wait` seconds."""
    found = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        try:
            sock.sendto(MAGIC, (target, port))
        except OSError:
            return []
        end = time.time() + wait
        while time.time() < end:
            try:
                msg, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                d = json.loads(msg.decode('utf-8'))
                if d.get('app') == 'mister-90s-tv' and d.get('id') != own_id:
                    found[d['id']] = {'id': d['id'], 'name': str(d.get('name', 'MiSTer'))[:24], 'host': addr[0],
                                      'port': int(d.get('port', 8090))}
            except (ValueError, TypeError, KeyError):
                continue
    finally:
        sock.close()
    return sorted(found.values(), key=lambda m: m['name'].lower())


# joining and following ---------------------------------------------------------------------------------------------------------
class ShareError(Exception):
    pass


def fetch(host, port, code, path, timeout=15):
    req = urllib.request.Request('http://%s:%d%s' % (host, port, path), headers={'X-Studio-Code': code})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise ShareError('Wrong code' if exc.code == 401 else 'The other MiSTer said error %d' % exc.code)
    except (OSError, ValueError) as exc:
        raise ShareError('Cannot reach the other MiSTer (%s)' % exc)


def join(data, host, port, code, name='', mister_id=''):
    """Copy the other MiSTer's files and remember it so they are kept up to date. -> its name."""
    bundle = fetch(host, port, code, '/api/share')
    try:
        unpack(bundle, data)
    except (ValueError, KeyError) as exc:
        raise ShareError(str(exc))
    note = {'host': host, 'port': int(port), 'code': code, 'name': name or host, 'id': mister_id, 'stamp': bundle['stamp']}
    write_atomic(os.path.join(data, 'join.json'), json.dumps(note).encode('utf-8'))
    return name or host


def following(data):
    j = read_json(os.path.join(data, 'join.json'), None)
    return j if isinstance(j, dict) and j.get('host') else None


def leave(data):
    try:
        os.unlink(os.path.join(data, 'join.json'))
    except OSError:
        pass


def check(data, log=print):
    """One follow step: ask the other MiSTer if its files changed and copy them if so. -> True when files were updated."""
    j = following(data)
    if not j:
        return False
    for attempt in (0, 1):
        try:
            if fetch(j['host'], j['port'], j['code'], '/api/share/stamp', 10).get('stamp') == j.get('stamp'):
                return False
            bundle = fetch(j['host'], j['port'], j['code'], '/api/share')
            unpack(bundle, data)
            j['stamp'] = bundle['stamp']
            write_atomic(os.path.join(data, 'join.json'), json.dumps(j).encode('utf-8'))
            log('sharing: updated from %s' % j.get('name'))
            return True
        except (ShareError, ValueError, KeyError) as exc:
            if attempt or not j.get('id') or 'reach' not in str(exc):
                log('sharing: %s' % exc)
                return False
            moved = [m for m in scan(device(data)['id']) if m['id'] == j['id']]          # its address may have changed
            if not moved:
                log('sharing: %s is not on the network' % j.get('name'))
                return False
            j['host'], j['port'] = moved[0]['host'], moved[0]['port']
    return False


def follow_in_background(data, log=print):
    def run():
        time.sleep(20)
        while True:
            try:
                check(data, log)
            except Exception as exc:                                               # never let the follower thread die
                log('sharing: %s' % exc)
            time.sleep(POLL_SECONDS)
    threading.Thread(target=run, name='share-follow', daemon=True).start()
