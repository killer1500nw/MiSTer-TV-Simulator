"""Studio: a local web page for building channels from Jellyfin and Plex libraries.

    python -m tvsim.studio        then open http://127.0.0.1:8090

Sources (servers and their credentials), indexed catalogs, your own lists and the channel spec all live in studio/ next to
the code. Listens on 127.0.0.1 only; every POST must carry the header X-Studio: 1 (a web page on another site cannot send it).
"""
import datetime as dt
import hmac
import json
import os
import secrets
import time
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import jellyfin, plex as plexlib
from ..schedule import Scheduler
from ..store import channels_to_json, items_from_catalog
from .compile import compile_all, compile_channel

ROOT = Path(__file__).resolve().parents[2]
# On the MiSTer the launcher sets C90_DATA to the player's folder: Studio keeps its files in <data>/studio and Build writes the
# channels straight into <data>, where the player reads them. On a PC (development) everything stays next to the code.
DATA = Path(os.environ['C90_DATA']) if os.environ.get('C90_DATA') else None
DEVICE = DATA is not None
STUDIO = (DATA / 'studio') if DEVICE else ROOT / 'studio'
CATALOGS = STUDIO / 'catalogs'
BUILD = DATA if DEVICE else ROOT / 'build'
PAGE = Path(__file__).with_name('index.html')
SECRET_KEYS = ('api_key', 'token')


def read_json(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path, obj, indent=1):
    """Write through a temporary file so a reader (the player) never sees half a file."""
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding='utf-8')
    os.replace(str(tmp), str(path))


def pairing_code():
    """The four digits shown on the TV; kept in <data>/pairing.json so the player can show the same ones."""
    path = DATA / 'pairing.json'
    try:
        code = json.loads(path.read_text(encoding='utf-8'))['code']
        if isinstance(code, str) and len(code) == 4 and code.isdigit():
            return code
    except (OSError, ValueError, KeyError):
        pass
    code = '%04d' % secrets.randbelow(10000)
    path.write_text(json.dumps({'code': code}), encoding='utf-8')
    return code


class State:
    def __init__(self):
        STUDIO.mkdir(parents=True, exist_ok=True)
        CATALOGS.mkdir(parents=True, exist_ok=True)
        self.code = pairing_code() if DEVICE else None
        self.fails, self.locked_until = [], 0.0
        self.lock = threading.RLock()
        self.migrate()
        self.reload()

    # sources -----------------------------------------------------------------------------------------------------------------
    def migrate(self):
        """Older versions kept one Jellyfin server in config.json and its catalog in catalog.json."""
        cfg = read_json(STUDIO / 'config.json', {})
        if 'sources' not in cfg:
            key = cfg.get('api_key') or os.environ.get('JELLYFIN_API_KEY', '')
            cfg = {'sources': [{'id': 'jf', 'type': 'jellyfin', 'name': 'Jellyfin', 'api_key': key,
                                'server': cfg.get('server', 'http://localhost:8096')}] if key else []}
            write_json(STUDIO / 'config.json', cfg)
        old = ROOT / 'catalog.json'
        if old.exists() and not (CATALOGS / 'jf.json').exists() and any(s['id'] == 'jf' for s in cfg['sources']):
            (CATALOGS / 'jf.json').write_text(old.read_text(encoding='utf-8'), encoding='utf-8')

    def sources(self):
        return read_json(STUDIO / 'config.json', {'sources': []})['sources']

    def source(self, sid):
        s = next((s for s in self.sources() if s['id'] == sid), None)
        if s is None:
            raise KeyError('no such source: %s' % sid)
        return s

    def save_source(self, body):
        """Add or update a source; a blank credential keeps the saved one. -> its id"""
        with self.lock:
            sources = self.sources()
            cur = next((s for s in sources if s['id'] == body.get('id')), None)
            kind = body['type']
            if kind not in ('jellyfin', 'plex'):
                raise ValueError('type must be jellyfin or plex')
            if cur is None:
                base = 'jf' if kind == 'jellyfin' else 'plex'
                sid, n = base, 1
                while any(s['id'] == sid for s in sources):
                    n += 1
                    sid = '%s%d' % (base, n)
                cur = {'id': sid, 'type': kind}
                sources.append(cur)
            cur['name'] = (body.get('name') or '').strip() or ('Jellyfin' if kind == 'jellyfin' else 'Plex')
            cur['server'] = (body.get('server') or '').strip().rstrip('/')
            field = 'api_key' if kind == 'jellyfin' else 'token'
            if (body.get(field) or '').strip():
                cur[field] = body[field].strip()
            write_json(STUDIO / 'config.json', {'sources': sources})
            return cur['id']

    def delete_source(self, sid):
        with self.lock:
            sources = [s for s in self.sources() if s['id'] != sid]
            write_json(STUDIO / 'config.json', {'sources': sources})
            (CATALOGS / ('%s.json' % sid)).unlink(missing_ok=True)
            self.reload()

    # Plex sign-in: the token never goes to the browser. The pin is remembered here, so approving in another tab (or on a phone that
    # puts this page to sleep, or even drops it) still ends with a saved sign-in.
    def plex_pin_start(self):
        pin = plexlib.pin_start()
        write_json(STUDIO / 'plex_pin.json', {'id': pin['id'], 'at': time.time()})
        return pin

    def plex_pin_check(self):
        """-> {'state': 'none' | 'pending' | 'expired' | 'signed_in', 'id': source id when signed in}"""
        path = STUDIO / 'plex_pin.json'
        pin = read_json(path, None)
        if not pin:
            return {'state': 'none'}
        if time.time() - pin['at'] > 900:
            path.unlink(missing_ok=True)
            return {'state': 'expired'}
        token = plexlib.pin_check(pin['id'])
        if not token:
            return {'state': 'pending'}
        with self.lock:
            sources = self.sources()
            src = next((s for s in sources if s['type'] == 'plex' and not s.get('token')), None)
            if src is None:
                src = next((s for s in sources if s['type'] == 'plex' and not s.get('server')), None)
            if src is None:
                sid, n = 'plex', 1
                while any(s['id'] == sid for s in sources):
                    n += 1
                    sid = 'plex%d' % n
                src = {'id': sid, 'type': 'plex', 'name': 'Plex', 'server': ''}
                sources.append(src)
            src['token'] = token
            write_json(STUDIO / 'config.json', {'sources': sources})
        path.unlink(missing_ok=True)
        return {'state': 'signed_in', 'id': src['id']}

    def plex_servers(self, sid):
        s = self.source(sid)
        if not s.get('token'):
            raise ValueError('Not signed in to Plex.')
        return plexlib.servers(s['token'])

    def client(self, s):
        if not s.get('server'):
            raise ValueError('This source has no server address.')
        if s['type'] == 'jellyfin':
            if not s.get('api_key'):
                raise ValueError('No Jellyfin API key or sign-in for this source.')
            return jellyfin.Jellyfin(s['server'], s['api_key'])
        if not s.get('token'):
            raise ValueError('Not signed in to Plex.')
        return plexlib.Plex(s['server'], s['token'])

    def test_source(self, sid):
        s = self.source(sid)
        c = self.client(s)
        if s['type'] == 'jellyfin':
            info = c.get('/System/Info/Public')
            c.get('/Items', Limit=1, Recursive='true')            # fails (401/403) when the key or sign-in is not accepted
            return 'Connected to %s (Jellyfin %s).' % (info.get('ServerName', '?'), info.get('Version', '?'))
        info = c.identity()
        return 'Connected to %s (Plex %s), %d libraries.' % (info.get('friendlyName', '?'), info.get('version', '?'), len(c.sections()))

    def index_source(self, sid):
        s = self.source(sid)
        c = self.client(s)
        if s['type'] == 'jellyfin':
            from .. import indexer
            cat = indexer.build(c, log=lambda m: None, slug=sid)
        else:
            from .. import plexindex
            cat = plexindex.build(c, log=lambda m: None, slug=sid)
        with self.lock:
            write_json(CATALOGS / ('%s.json' % sid), cat)
            self.reload()
        return '%s: %d items, %d groups.' % (s['name'], len(cat['items']), len(cat['groups']))

    # catalogs, lists and what is hidden ----------------------------------------------------------------------------------------
    def reload(self):
        with self.lock:
            self.items, self.groups, self.generated = {}, {}, {}
            for s in self.sources():
                cat = read_json(CATALOGS / ('%s.json' % s['id']), None)
                if cat is None:
                    continue
                self.items.update(cat['items'])
                self.generated[s['id']] = cat.get('generated', '')
                for g in cat['groups']:
                    g.setdefault('source', s['id'])            # catalogs written before sources existed
                    self.groups[g['id']] = g
            lib = read_json(STUDIO / 'library.json', {})
            self.lists = lib.get('lists', [])
            self.hidden_groups = set(lib.get('hidden_groups', []))
            self.hidden_items = set(lib.get('hidden_items', []))
            self.catalog = {'items': self.items}
            self.all_groups = dict(self.groups)
            for lst in self.lists:
                self.all_groups[lst['id']] = {'id': lst['id'], 'type': 'list', 'name': lst['name'], 'source': '',
                                              'item_ids': [i for i in lst['item_ids'] if i in self.items]}

    def save_library(self):
        write_json(STUDIO / 'library.json', {'lists': self.lists, 'hidden_groups': sorted(self.hidden_groups),
                                             'hidden_items': sorted(self.hidden_items)})
        self.reload()

    def library_action(self, body):
        with self.lock:
            act = body['action']
            ids = [i for i in body.get('item_ids', []) if i in self.items]
            lst = next((l for l in self.lists if l['id'] == body.get('id')), None)
            if act == 'list_create':
                n = 1 + max([int(l['id'].split(':')[1]) for l in self.lists] + [0])
                self.lists.append({'id': 'my:%d' % n, 'name': (body.get('name') or 'New list').strip(), 'item_ids': ids})
                result = 'my:%d' % n
            elif lst is None and act.startswith('list_'):
                raise KeyError('no such list')
            elif act == 'list_rename':
                lst['name'] = (body.get('name') or lst['name']).strip()
            elif act == 'list_delete':
                self.lists.remove(lst)
            elif act == 'list_add':
                lst['item_ids'] += [i for i in ids if i not in lst['item_ids']]
            elif act == 'list_remove':
                lst['item_ids'] = [i for i in lst['item_ids'] if i not in ids]
            elif act == 'hide':
                self.hidden_items |= set(ids)
                self.hidden_groups |= set(g for g in body.get('group_ids', []) if g in self.all_groups)
            elif act == 'unhide':
                self.hidden_items -= set(body.get('item_ids', []))
                self.hidden_groups -= set(body.get('group_ids', []))
            else:
                raise ValueError('unknown action')
            self.save_library()
            return result if act == 'list_create' else 'ok'

    # channel spec ------------------------------------------------------------------------------------------------------------
    def spec(self):
        return read_json(STUDIO / 'spec.json', {'channels': []})

    def save_spec(self, spec):
        write_json(STUDIO / 'spec.json', spec)

    def stats(self, spec):
        return compile_all(spec, self.catalog, self.all_groups, self.hidden_items)[2]

    def player_config(self):
        """What the player needs to reach each source (on the MiSTer, Studio is the only place these live)."""
        cfg = read_json(BUILD / 'config.json', {})
        cfg.setdefault('chain', True)
        cfg['sources'] = {s['id']: {k: s[k] for k in ('type', 'server', 'api_key', 'token', 'transcode') if k in s}
                          for s in self.sources() if s.get('server') and (s.get('api_key') or s.get('token'))}
        return cfg

    def refine_used(self, spec):
        """Plex only guesses 'interlaced' from NTSC/PAL in its listing. For the items the channels really use, ask the server for the
        real scan type once and keep the answer in the catalog (a few hundred requests, not thousands, and never at index time)."""
        from .. import plexindex
        from concurrent.futures import ThreadPoolExecutor
        _, used, _ = compile_all(spec, self.catalog, self.all_groups, self.hidden_items)
        todo = [self.items[i['id']] for i in used if self.items.get(i['id'], {}).get('unchecked')]
        if not todo:
            return 0
        by_source = {}
        for rec in todo:
            by_source.setdefault(rec['id'].split(':', 1)[0], []).append(rec)
        done = 0
        for sid, recs in by_source.items():
            try:
                src = self.source(sid)
                client = self.client(src)
            except (KeyError, ValueError):
                continue
            with ThreadPoolExecutor(4) as pool:
                fresh = list(pool.map(lambda r: plexindex.refine(client, dict(r, video=dict(r.get('video') or {}))), recs))
            path = CATALOGS / ('%s.json' % sid)
            cat = read_json(path, None)
            if cat is None:
                continue
            for rec in fresh:
                cat['items'][rec['id']].update(direct_ok=rec['direct_ok'], why=rec['why'], unchecked=rec['unchecked'],
                                               video=rec.get('video', cat['items'][rec['id']].get('video')))
            with self.lock:
                write_json(path, cat, None)
                self.reload()
            done += len(fresh)
        return done

    def build(self, spec):
        try:
            self.refine_used(spec)
        except Exception:                                    # a server that cannot be asked just leaves those items on the safe side
            pass
        channels, items, stats = compile_all(spec, self.catalog, self.all_groups, self.hidden_items)
        BUILD.mkdir(parents=True, exist_ok=True)
        write_json(BUILD / 'runtime_catalog.json', {'items': items}, None)
        if DEVICE:
            write_json(BUILD / 'config.json', self.player_config())
        write_json(BUILD / 'channels.json', channels_to_json(channels), None)       # last: the player reloads when this changes
        warn = [s['name'] for s in self.sources() if DEVICE and ('//localhost' in s.get('server', '') or '//127.0.0.1' in s.get('server', ''))]
        built = {c.number for c in channels}
        skipped = [c['number'] for c in spec.get('channels', []) if c['number'] not in built]
        return {'channels': len(channels), 'items': len(items), 'stats': stats, 'warn_local': warn, 'skipped': skipped}

    def push(self, stop=False):
        cmd = [sys.executable, str(ROOT / 'tools' / 'deploy_player.py')] + (['--stop'] if stop else [])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        out = (r.stdout + r.stderr).strip()
        return '\n'.join(l for l in out.splitlines() if not l.startswith('**'))

    def preview(self, number, date):
        spec = next((c for c in self.spec()['channels'] if c['number'] == number), None)
        if spec is None:
            raise KeyError('no such channel')
        ch, _ = compile_channel(spec, self.catalog, self.all_groups, self.hidden_items)
        sched = Scheduler(items_from_catalog(self.catalog))
        return [{'start': a.start, 'end': a.end, 'title': a.item.title, 'show': a.item.show, 'kind': a.item.kind,
                 'direct': a.item.direct_ok, 'slot': a.slot, 'ad': sched.is_ad(ch, a.item)} for a in sched.day(ch, date)]

    # what the page shows -----------------------------------------------------------------------------------------------------
    def item_row(self, i):
        it = self.items[i]
        return {'id': i, 'title': it['title'], 'show': it['show'], 'mins': round(it['duration'] / 60), 'direct': it['direct_ok'],
                'source': i.split(':', 1)[0], 'hidden': i in self.hidden_items}

    def group_items(self, gid, q, show_hidden, limit=300):
        g = self.all_groups.get(gid)
        if not g:
            return []
        q = (q or '').lower()
        out = []
        for i in g['item_ids']:
            if i in self.hidden_items and not show_hidden:
                continue
            it = self.items[i]
            if q and q not in (it['show'] + ' ' + it['title']).lower():
                continue
            out.append(self.item_row(i))
            if len(out) >= limit:
                break
        return out

    def search(self, q, source, show_hidden, limit=150):
        q = (q or '').lower().strip()
        if not q:
            return []
        out = []
        for i, it in self.items.items():
            if source and not i.startswith(source + ':'):
                continue
            if i in self.hidden_items and not show_hidden:
                continue
            if q in (it['show'] + ' ' + it['title']).lower():
                out.append(self.item_row(i))
                if len(out) >= limit:
                    break
        return out

    def overview(self):
        spec = self.spec()
        groups = []
        for g in self.all_groups.values():
            vis = [i for i in g['item_ids'] if i in self.items]
            groups.append({'id': g['id'], 'type': g['type'], 'name': g['name'], 'source': g['source'], 'count': len(vis),
                           'hours': round(sum(self.items[i]['duration'] for i in vis) / 3600.0, 1), 'hidden': g['id'] in self.hidden_groups})
        srcs = []
        for s in self.sources():
            srcs.append({'id': s['id'], 'type': s['type'], 'name': s['name'], 'server': s.get('server', ''),
                         'has_credential': bool(s.get('api_key') or s.get('token')), 'indexed': self.generated.get(s['id'], ''),
                         'items': sum(1 for i in self.items if i.startswith(s['id'] + ':'))})
        return {'sources': srcs, 'groups': groups, 'spec': spec, 'stats': self.stats(spec), 'hidden_items': len(self.hidden_items),
                'device': DEVICE}


def make_handler(state):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, obj, code=200, ctype='application/json'):
            body = obj.encode('utf-8') if isinstance(obj, str) else json.dumps(obj).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', ctype + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            """On the MiSTer every API call needs the four-digit code shown on the TV (ten wrong guesses lock it for a minute)."""
            if state.code is None:
                return True
            now = time.time()
            if now < state.locked_until:
                return False
            if hmac.compare_digest(self.headers.get('X-Studio-Code', ''), state.code):
                return True
            state.fails = [t for t in state.fails if now - t < 60] + [now]
            if len(state.fails) >= 10:
                state.locked_until, state.fails = now + 60, []
            time.sleep(0.5)
            return False

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            hidden = q.get('hidden') == '1'
            try:
                if u.path == '/':
                    return self.reply(PAGE.read_text(encoding='utf-8'), ctype='text/html')
                if u.path == '/api/ping':
                    return self.reply({'device': DEVICE, 'needs_code': state.code is not None})
                if u.path.startswith('/api/') and not self.authorized():
                    return self.reply({'error': 'code'}, 401)
                if u.path == '/api/state':
                    return self.reply(state.overview())
                if u.path == '/api/group':
                    return self.reply(state.group_items(q.get('id', ''), q.get('q', ''), hidden))
                if u.path == '/api/search':
                    return self.reply(state.search(q.get('q', ''), q.get('source', ''), hidden))
                if u.path == '/api/preview':
                    return self.reply(state.preview(int(q['channel']), dt.date.fromisoformat(q['date'])))
                self.reply({'error': 'not found'}, 404)
            except (KeyError, ValueError) as exc:
                self.reply({'error': str(exc)}, 400)

        def do_POST(self):
            if self.headers.get('X-Studio') != '1':
                return self.reply({'error': 'missing X-Studio header'}, 403)
            if not self.authorized():
                return self.reply({'error': 'code'}, 401)
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(n) or b'{}')
            u = urlparse(self.path).path
            try:
                if u == '/api/spec':
                    state.save_spec(body)
                    return self.reply({'stats': state.stats(body)})
                if u == '/api/build':
                    state.save_spec(body)
                    return self.reply(state.build(body))
                if u == '/api/push':
                    state.save_spec(body)
                    built = state.build(body)
                    if DEVICE:                                       # nothing to copy: the player is on this machine and reloads by itself
                        note = (' Left out because they have no items: %s.' % ', '.join(str(n) for n in built['skipped'])) if built['skipped'] else ''
                        return self.reply({'output': 'Applied: %d channels. The TV switches over in a few seconds.%s' % (built['channels'], note)})
                    return self.reply({'output': state.push()})
                if u == '/api/stop':
                    if DEVICE:
                        return self.reply({'output': 'Press BACK twice on the pad or keyboard to leave the player.'})
                    return self.reply({'output': state.push(stop=True)})
                if u == '/api/library':
                    return self.reply({'result': state.library_action(body)})
                if u == '/api/source/save':
                    return self.reply({'id': state.save_source(body)})
                if u == '/api/source/delete':
                    state.delete_source(body['id'])
                    return self.reply({'ok': True})
                if u == '/api/source/test':
                    return self.reply({'message': state.test_source(body['id'])})
                if u == '/api/source/index':
                    return self.reply({'message': state.index_source(body['id'])})
                if u == '/api/jellyfin/login':
                    return self.reply({'token': jellyfin.authenticate(body['server'], body['username'], body['password'])})
                if u == '/api/plex/pin':
                    return self.reply(state.plex_pin_start())
                if u == '/api/plex/pin_check':
                    return self.reply(state.plex_pin_check())
                if u == '/api/plex/servers':
                    return self.reply({'servers': state.plex_servers(body['id'])})
                self.reply({'error': 'not found'}, 404)
            except Exception as exc:                       # shown in the page
                self.reply({'error': '%s: %s' % (type(exc).__name__, exc)}, 500)
    return H


def main():
    port = int(os.environ.get('STUDIO_PORT', '8090'))
    state = State()
    host = os.environ.get('STUDIO_HOST') or ('0.0.0.0' if DEVICE else '127.0.0.1')     # on the MiSTer: reachable from the home network
    srv = ThreadingHTTPServer((host, port), make_handler(state))
    print('Studio: http://%s:%d  (Ctrl-C to stop)%s' % (host, port, '  code ' + state.code if state.code else ''), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
