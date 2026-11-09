"""Minimal Jellyfin REST client (standard library only). The API key comes from the
caller (environment); it is sent as a header and is never written to the catalog."""
import json
import urllib.parse
import urllib.request


class Jellyfin:
    def __init__(self, base, key, timeout=60):
        self.base, self.key, self.timeout = base.rstrip('/'), key, timeout

    def get(self, path, **params):
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request('%s%s%s' % (self.base, path, '?' + q if q else ''),
                                     headers={'Authorization': 'MediaBrowser Token="%s"' % self.key})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def items(self, page=500, **params):
        """Every item matching `params`, fetched page by page."""
        start = 0
        while True:
            d = self.get('/Items', StartIndex=start, Limit=page, **params)
            rows = d.get('Items', [])
            yield from rows
            start += len(rows)
            if not rows or start >= d.get('TotalRecordCount', 0):
                return

    def libraries(self):
        return self.get('/Library/VirtualFolders')

    def playlist_items(self, playlist_id):
        return self.get('/Playlists/%s/Items' % playlist_id).get('Items', [])


def authenticate(base, username, password, timeout=30):
    """Sign in with a Jellyfin user name and password -> an access token (the password is not kept)."""
    body = json.dumps({'Username': username, 'Pw': password}).encode()
    req = urllib.request.Request(
        base.rstrip('/') + '/Users/AuthenticateByName', data=body, method='POST',
        headers={'Content-Type': 'application/json',
                 'Authorization': 'MediaBrowser Client="MiSTer 90s TV Simulator", Device="PC", DeviceId="mister-90s-tv-studio", Version="1.0"'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)['AccessToken']
