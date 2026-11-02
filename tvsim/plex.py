"""Minimal Plex Media Server client (standard library only), plus plex.tv sign-in (PIN link flow).

The token is sent as a header and is never written to a catalog."""
import json
import urllib.parse
import urllib.request

from .plexurl import CLIENT_ID, PRODUCT

PAGE = 200


class Plex:
    def __init__(self, base, token, timeout=60):
        self.base, self.token, self.timeout = base.rstrip('/'), token, timeout

    def get(self, path, **params):
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request('%s%s%s' % (self.base, path, '?' + q if q else ''),
                                     headers={'X-Plex-Token': self.token, 'Accept': 'application/json',
                                              'X-Plex-Client-Identifier': CLIENT_ID, 'X-Plex-Product': PRODUCT})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r).get('MediaContainer', {})

    def rows(self, path, key='Metadata', **params):
        """Every entry under `path`, fetched page by page."""
        start = 0
        while True:
            d = self.get(path, **dict(params, **{'X-Plex-Container-Start': start, 'X-Plex-Container-Size': PAGE}))
            rows = d.get(key, [])
            yield from rows
            start += len(rows)
            if not rows or start >= d.get('totalSize', d.get('size', 0)):
                return

    def identity(self):
        return self.get('/')

    def sections(self):
        return self.get('/library/sections').get('Directory', [])


# plex.tv sign-in: the user opens a link, approves, and the app collects a token ------------------------------------------
def _tv(path, method='GET', token='', **params):
    headers = {'Accept': 'application/json', 'X-Plex-Client-Identifier': CLIENT_ID, 'X-Plex-Product': PRODUCT}
    if token:
        headers['X-Plex-Token'] = token
    req = urllib.request.Request('https://plex.tv' + path + ('?' + urllib.parse.urlencode(params) if params else ''),
                                 method=method, data=b'' if method == 'POST' else None, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def pin_start():
    """-> {'id', 'code', 'url'}: send the user to `url`."""
    j = _tv('/api/v2/pins', 'POST', strong='true')
    url = 'https://app.plex.tv/auth#?' + urllib.parse.urlencode(
        {'clientID': CLIENT_ID, 'code': j['code'], 'context[device][product]': PRODUCT})
    return {'id': j['id'], 'code': j['code'], 'url': url}


def pin_check(pin_id):
    """-> the auth token once the user has approved, else None."""
    return _tv('/api/v2/pins/%s' % pin_id).get('authToken') or None


def servers(token):
    """-> [{'name', 'connections': [{'uri', 'local'}]}] for the Plex servers this account can reach."""
    out = []
    for r in _tv('/api/v2/resources', token=token, includeHttps=1, includeRelay=0):
        if 'server' in (r.get('provides') or ''):
            conns = []
            for c in r.get('connections', []):
                if c.get('relay'):
                    continue
                if c.get('local') and c.get('address') and c.get('port'):
                    # the MiSTer needs a plain address it can reach without a certificate or a DNS lookup
                    conns.append({'uri': 'http://%s:%s' % (c['address'], c['port']), 'local': True})
                conns.append({'uri': c['uri'], 'local': bool(c.get('local'))})
            out.append({'name': r.get('name', ''), 'connections': sorted(conns, key=lambda c: (not c['local'], c['uri'].startswith('https')))})
    return out
