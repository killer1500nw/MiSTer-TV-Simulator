"""PC check of a Plex transcode through the chain feeder (needs a Plex source in studio/config.json and an ffmpeg).

    python tests/plex_pc_check.py FFMPEG plex2:8439 [offset seconds]
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim import streams
from tvsim.model import Item
from tvsim.player import h264feed as hf
from tvsim.player.chain import ChainFeeder, Entry


class RT:
    def __init__(self, ff):
        self.ffmpeg, self.ca = ff, ''


def main():
    rt, item_id, off = RT(sys.argv[1]), sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    here = os.path.join(os.path.dirname(__file__), '..')
    cfg = streams.normalize({'sources': {s['id']: s for s in json.load(open(os.path.join(here, 'studio', 'config.json')))['sources']}})
    cat = json.load(open(os.path.join(here, 'studio', 'catalogs', item_id.split(':')[0] + '.json'), encoding='utf-8'))
    rec = cat['items'][item_id]
    item = Item(rec['id'], rec['title'], rec['duration'], direct_ok=rec['direct_ok'], media=rec.get('media', ''))
    st = streams.stream(cfg, item, off, '%032x' % int(time.time() * 1000))
    vsrc, asrc = {'url': st.video_url, 'headers': {}}, {'url': st.audio_url, 'headers': {}}

    def vcmd(s):
        st.prepare and st.prepare('v')
        return hf.video_copy_command(rt, vsrc, s)

    def acmd(s):
        st.prepare and st.prepare('a')
        cmd = hf.audio_pcm_command(rt, asrc, s if st.audio_seekable else 0.0)
        return cmd
    f = ChainFeeder(None, [Entry(item.title, vcmd, acmd, st.seek_s, audio_early=not st.audio_seekable)], log=print)
    t0 = time.time()
    f.start()
    f._start_audio(0)
    got_v, got_a, first_v = [], [], None
    end = time.time() + 25                                    # a taste of the stream is enough
    import queue
    while time.time() < end:
        try:
            x = f.vq.get(timeout=0.5)
            if x is not None:
                got_v.append(x[0])
                first_v = first_v or time.time() - t0
        except queue.Empty:
            pass
        try:
            y = f.aq.get_nowait()
            if y is not None:
                got_a.append(y[0])
        except queue.Empty:
            pass
    f.close()
    print('first picture after %.1f s; video AUs %d (pts %.2f..%.2f s); audio chunks %d (pts %.2f..%.2f s)' % (
        first_v or -1, len(got_v), min(got_v, default=0) / 90000.0, max(got_v, default=0) / 90000.0,
        len(got_a), min(got_a, default=0) / 90000.0, max(got_a, default=0) / 90000.0))


main()
