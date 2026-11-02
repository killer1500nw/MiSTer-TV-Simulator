"""Stream URLs for a Plex item: the file itself (direct), or Plex's own transcoder as HLS the core can take.

Plex's transcoder only starts a session it has already 'decided' (a /decision request with the same parameters), and it
only knows client profiles by platform name, so the requests present themselves as the Plex Web client (platform Chrome)
and add limits through X-Plex-Client-Profile-Extra: H.264, AAC stereo, 854x480, direct play and direct stream off so even a
Baseline file is really re-encoded. Found out from the server's own log (see tests/test_plex.py for the shape).
"""
import threading
import urllib.parse
import urllib.request

PRODUCT = 'MiSTer 90s TV Simulator'
CLIENT_ID = 'mister-90s-tv-simulator'
START = '/video/:/transcode/universal/start.m3u8'
DECISION = '/video/:/transcode/universal/decision'
PROFILE_EXTRA = ('add-transcode-target(type=videoProfile&context=streaming&protocol=hls&container=mpegts'
                 '&videoCodec=h264&audioCodec=aac)'
                 '+add-limitation(scope=videoCodec&scopeName=h264&type=upperBound&name=video.level&value=41&isRequired=true)'
                 '+add-limitation(scope=videoAudioCodec&scopeName=aac&type=upperBound&name=audio.channels&value=2&isRequired=true)')
TRANSCODE = dict(videoResolution='854x480', maxVideoBitrate=2500, audioBoost=100, subtitleSize=100, subtitles='none')


def headers_params(src):
    return {'X-Plex-Token': src['token'], 'X-Plex-Client-Identifier': CLIENT_ID, 'X-Plex-Product': 'Plex Web',
            'X-Plex-Version': '4.100.0', 'X-Plex-Platform': 'Chrome', 'X-Plex-Platform-Version': '120.0',
            'X-Plex-Device': 'Windows'}


def _query(src, raw, offset_s, session):
    q = dict(TRANSCODE)
    q.update(src.get('transcode', {}))
    q.update(hasMDE=1, path='/library/metadata/%s' % raw, mediaIndex=0, partIndex=0, protocol='hls', directPlay=0,
             directStream=0, fastSeek=1, location='lan', offset=int(offset_s), session=session, **headers_params(src))
    q['X-Plex-Session-Identifier'] = session
    q['X-Plex-Client-Profile-Extra'] = PROFILE_EXTRA
    return urllib.parse.urlencode(q)


def stream(src, item, offset_s, session):
    """-> (video url, audio url, seek seconds for ffmpeg, prepare). `prepare(kind)` ('v' or 'a') must be called just before ffmpeg
    opens that url: it asks Plex to decide the transcode session (a no-op for a direct file)."""
    raw = item.id.split(':', 1)[1]
    base = src['server'].rstrip('/')
    if item.direct_ok and item.media:
        url = '%s%s?%s' % (base, item.media, urllib.parse.urlencode({'X-Plex-Token': src['token']}))
        return url, url, float(offset_s), None
    sess = session + 'a1'                                      # one transcode session: its stream carries the picture AND the sound
    decided, lock = [], threading.Lock()

    def prepare(kind):
        with lock:                                             # picture and sound start together: the second waits for the first's answer
            if decided:
                return
            url = '%s%s?%s' % (base, DECISION, _query(src, raw, offset_s, sess))
            with urllib.request.urlopen(url, timeout=30) as r:
                r.read(2000)
            decided.append(kind)
    url = '%s%s?%s' % (base, START, _query(src, raw, offset_s, sess))
    return url, url, 0.0, prepare
