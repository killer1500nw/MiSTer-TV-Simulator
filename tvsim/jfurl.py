"""Stream URLs for a Jellyfin item: direct (the file as is) or a server transcode the core can take."""
import urllib.parse

TRANSCODE = dict(Container='ts', VideoCodec='h264', AudioCodec='aac', MaxWidth=854, MaxHeight=480,
                 VideoBitRate=2500000, AudioBitRate=128000, MaxAudioChannels=2, MaxFramerate=30, AllowVideoStreamCopy='false')


def stream(cfg, item, offset_s, session):
    """-> (url, seek seconds for ffmpeg). A direct file is sought by ffmpeg; a transcode starts at the offset on the server."""
    raw = item.id.split(':', 1)[1]
    base = '%s/Videos/%s/' % (cfg['server'].rstrip('/'), raw)
    if item.direct_ok:
        return base + 'stream?' + urllib.parse.urlencode(dict(Static='true', api_key=cfg['api_key'])), float(offset_s)
    q = dict(TRANSCODE)
    q.update(cfg.get('transcode', {}))
    q.update(api_key=cfg['api_key'], PlaySessionId=session)
    if offset_s > 0:
        q['StartTimeTicks'] = int(offset_s * 10_000_000)
    return base + 'stream.ts?' + urllib.parse.urlencode(q), 0.0
