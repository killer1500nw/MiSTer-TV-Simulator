"""Stream URLs for a Jellyfin item: direct (the file as is) or a server transcode the core can take."""
import urllib.parse

TRANSCODE = dict(Container='ts', VideoCodec='h264', AudioCodec='aac', MaxWidth=854, MaxHeight=480,
                 VideoBitRate=2500000, AudioBitRate=128000, MaxAudioChannels=2, MaxFramerate=30, AllowVideoStreamCopy='false')


def stream(cfg, item, offset_s, session):
    """-> (url, seek seconds for ffmpeg, headers). Direct files are sought by ffmpeg; transcodes start at the server offset."""
    raw = item.id.split(':', 1)[1]
    base = '%s/Videos/%s/' % (cfg['server'].rstrip('/'), raw)
    headers = {'Authorization': 'MediaBrowser Token="%s"' % cfg['api_key']}
    if item.direct_ok:
        return base + 'stream?' + urllib.parse.urlencode(dict(Static='true')), float(offset_s), headers
    q = dict(TRANSCODE)
    q.update(cfg.get('transcode', {}))
    # Credentials belong in the header, even if an older transcode override included them.
    q = {k: v for k, v in q.items() if k.lower() not in ('api_key', 'apikey', 'x-emby-token')}
    q.update(PlaySessionId=session)
    if offset_s > 0:
        q['StartTimeTicks'] = int(offset_s * 10_000_000)
    return base + 'stream.ts?' + urllib.parse.urlencode(q), 0.0, headers
