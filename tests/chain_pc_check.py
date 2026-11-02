"""PC check of the chain's time stamp rebasing with two generated clips (needs an ffmpeg with libx264; not part of the unit tests).

    python tests/chain_pc_check.py FFMPEG a.mp4 b.mp4
"""
import os
import queue
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.player import h264feed as hf
from tvsim.player.chain import ChainFeeder, Entry


class RT:
    def __init__(self, ff):
        self.ffmpeg, self.ca = ff, ''


def drain(q):
    out = []
    while True:
        item = q.get(timeout=15)
        if item is None:
            return out
        out.append(item)


def main():
    rt = RT(sys.argv[1])
    entries = []
    for path in sys.argv[2:]:
        src = {'url': path, 'headers': {}}
        entries.append(Entry(path, lambda s, src=src: hf.video_copy_command(rt, src, s),
                             lambda s, src=src: hf.audio_pcm_command(rt, src, s), 0.0))
    f = ChainFeeder(None, entries, log=print)
    f.start()
    f._start_audio(0)
    v = drain(f.vq)
    a = drain(f.aq)
    f.close()
    vp = [p for p, _ in v]
    print('video: %d AUs, pts %.3f .. %.3f s' % (len(v), min(vp) / 90000.0, max(vp) / 90000.0))
    srt = sorted(vp)
    gaps = [(b - a_) / 90000.0 for a_, b in zip(srt, srt[1:])]
    print('largest gap between pictures %.3f s, smallest %.3f s' % (max(gaps), min(gaps)))
    ap = [p for p, _ in a]
    print('audio: %d chunks, pts %.3f .. %.3f s (%.1f s of sound)' % (len(a), min(ap) / 90000.0, max(ap) / 90000.0, len(a) * 0.1))
    print('audio chunk order ok:', all(x < y for x, y in zip(ap, ap[1:])))
    print('chunk spacing min/max: %.3f / %.3f' % (min(y - x for x, y in zip(ap, ap[1:])) / 90000.0, max(y - x for x, y in zip(ap, ap[1:])) / 90000.0))


main()
