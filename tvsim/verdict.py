"""Can the MiSTer H.264 core decode this video stream directly, or must a server transcode it?

Limits come from owenb321's core docs and our spike (2026-11-02):
  * H.264 Main or High, 8-bit 4:2:0 (Baseline/CAVLC produced no picture in the spike)
  * at most 1280x720, and at most 108,000 macroblocks per second
    (720p30 and 480p60 both fit; 720p60 and 1080p do not)
  * about 8 Mbit/s at most
  * interlaced sources go to the transcoder (the core's handling is unproven)
"""
MAX_MB_PER_SEC = 108000
MAX_BITRATE = 8_000_000
MAX_W, MAX_H = 1280, 720


def verdict(v):
    """v: a Jellyfin video MediaStream dict (or None). -> (direct_ok, reason)."""
    if not v:
        return False, 'no video stream'
    codec = (v.get('Codec') or '').lower()
    if codec != 'h264':
        return False, 'codec %s' % (codec or 'unknown')
    profile = (v.get('Profile') or '').lower()
    if profile not in ('main', 'high'):
        return False, 'profile %s' % (v.get('Profile') or 'unknown')
    if (v.get('BitDepth') or 8) > 8 or (v.get('PixelFormat') or 'yuv420p') != 'yuv420p':
        return False, 'not 8-bit 4:2:0'
    if v.get('IsInterlaced'):
        return False, 'interlaced'
    w, h = v.get('Width') or 0, v.get('Height') or 0
    if not w or not h:
        return False, 'unknown size'
    if w > MAX_W or h > MAX_H:
        return False, 'size %dx%d' % (w, h)
    fps = v.get('RealFrameRate') or v.get('AverageFrameRate') or 0
    if not fps:
        return False, 'unknown frame rate'
    mbs = -(-w // 16) * -(-h // 16) * fps
    if mbs > MAX_MB_PER_SEC:
        return False, 'too fast (%dx%d at %.0f fps)' % (w, h, fps)
    if (v.get('BitRate') or 0) > MAX_BITRATE:
        return False, 'bitrate %.1f Mbit/s' % (v['BitRate'] / 1e6)
    return True, 'ok'
