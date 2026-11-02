"""Stream URLs for any source (Jellyfin or Plex), and the player's config format.

Player config (config.json on the MiSTer):
  {"chain": true, "sources": {"jf": {"type": "jellyfin", "server": "http://...", "api_key": "..."},
                              "plex": {"type": "plex", "server": "http://...:32400", "token": "..."}}}
An item id is "<source id>:<server's own id>". Older configs ({"server", "api_key"}) mean the source "jf".
"""
from . import jfurl, plexurl


def normalize(cfg):
    if 'sources' not in cfg:
        cfg = dict(cfg, sources={'jf': {'type': 'jellyfin', 'server': cfg['server'], 'api_key': cfg['api_key']}})
    return cfg


def source_of(cfg, item):
    sid = item.id.split(':', 1)[0]
    try:
        return cfg['sources'][sid]
    except KeyError:
        raise RuntimeError('No source "%s" in the player config (item %s).' % (sid, item.title))


class Stream:
    """How to fetch one item: `video_url` / `audio_url` (they differ when a server would treat the audio request as the same
    transcode session as the video one), `seek_s` for ffmpeg, `prepare(kind)` to call just before opening a url (or None),
    and `audio_seekable`: False when the sound comes from a stream ffmpeg cannot seek into (it then starts where the picture does)."""

    def __init__(self, video_url, audio_url, seek_s=0.0, prepare=None, audio_seekable=True):
        self.video_url, self.audio_url, self.seek_s, self.prepare, self.audio_seekable = video_url, audio_url, seek_s, prepare, audio_seekable


def stream(cfg, item, offset_s, session):
    src = source_of(cfg, item)
    if src['type'] == 'plex':
        v, a, seek, prepare = plexurl.stream(src, item, offset_s, session)
        return Stream(v, a, seek, prepare, audio_seekable=prepare is None)       # a Plex transcode is HLS: start it, do not seek in it
    url, seek = jfurl.stream(src, item, offset_s, session)
    return Stream(url, url, seek)
