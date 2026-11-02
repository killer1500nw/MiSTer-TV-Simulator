"""Gapless playback of a list of clips (a programme, its ads, the next programme...) in ONE core session.

The core is fed access units with 90 kHz time stamps. Each clip's own time stamps are shifted so that it starts right where
the previous one ended; nothing tells the core a clip ended, so there is no new session, no flush and no gap. The writer
loop in h264feed.Feeder is reused unchanged: it just sees one long video and one long sound track.

Every clip should start with a keyframe (ffmpeg copies from the start of the file, or from a seek, which the feeder already
relies on). Video readers run ahead of playback by the size of the queues, so the next clip's ffmpeg is already running (and
has produced its first picture) well before the clip before it finishes.
"""
import collections
import threading
import time

from . import h264feed as hf
from . import h264sps
from .tsdemux import TsVideo

CLOCK = hf.CLOCK
HOLD_CHUNKS = 4                       # the newest sound chunks of a clip are held back until the next clip's start time is known


class Entry:
    """One clip: `video_cmd(start_s)` and `audio_cmd(start_s)` return ffmpeg command lines; `seek_s` is where it starts."""

    def __init__(self, title, video_cmd, audio_cmd, seek_s=0.0, crop=None, audio_early=False):
        self.title, self.video_cmd, self.audio_cmd, self.seek_s = title, video_cmd, audio_cmd, seek_s
        self.audio_early = audio_early                     # True: the sound does not need the picture's start time, so it may start at once
        self.crop = crop                                   # crop steps for h264sps.crop_shape, or None / [] for the whole picture


class ChainFeeder(hf.Feeder):
    def __init__(self, ring, entries, log=print, **kw):
        super().__init__(ring, None, None, log=log, **kw)
        self.entries = entries
        self.audio_cmd = True                              # (not None: the writer waits for sound)
        self.all_procs = []
        self.cond = threading.Condition()
        self.infos = {}                                    # entry index -> (first local pts, global start pts) or None (skipped)
        self.position = 0                                  # the clip whose pictures the video reader is on now
        self.t0 = time.monotonic()
        self.marks = {}                                    # when the first picture and first sound arrived (seconds after the start)

    def _spawn(self, kind, cmd):
        proc = super()._spawn(kind, cmd)
        self.all_procs.append(proc)
        return proc

    def close(self):
        self.stopping.set()
        with self.cond:
            self.cond.notify_all()
        for proc in self.all_procs:
            try:
                proc.kill()
            except (OSError, AttributeError):
                pass
        for proc in self.all_procs:
            try:
                proc.wait(timeout=2)
            except Exception:
                pass

    # video ---------------------------------------------------------------------------------------------------------------
    def start(self, start_s=0.0):
        t = threading.Thread(target=self._chain_video, daemon=True)
        t.start()
        self.threads.append(t)
        self._start_audio(0)                               # the sound thread waits for each clip's picture start where it must

    def _start_audio_thread(self):
        t = threading.Thread(target=self._chain_audio, daemon=True)
        t.start()
        self.threads.append(t)

    def _publish(self, idx, info):
        with self.cond:
            self.infos[idx] = info
            self.cond.notify_all()

    def _chain_video(self):
        next_start = None
        try:
            for idx, e in enumerate(self.entries):
                if self.stopping.is_set():
                    break
                self.position = idx
                proc = self._spawn('video', e.video_cmd(e.seek_s))
                demux = TsVideo()
                first = offset = None
                count, newest, start_g = 0, 0, 0
                while not self.stopping.is_set():
                    data = proc.stdout.read(188 * 128)
                    units = demux.feed(data) if data else demux.flush()
                    for pts, dts, au in units:
                        if pts is None:
                            continue
                        if first is None:
                            first = pts
                            self.marks.setdefault('video', time.monotonic() - self.t0)
                            start_g = first if next_start is None else next_start
                            offset = start_g - first
                            self._publish(idx, (first, start_g))
                        if e.crop:
                            au = h264sps.crop_access_unit(au, e.crop)
                        g = pts + offset
                        if not self._put(self.vq, (g, au)):
                            return
                        count += 1
                        newest = max(newest, g)
                    if not data:
                        break
                if first is None:
                    self.log('  clip %d (%s) gave no picture; skipped' % (idx, e.title))
                    self._publish(idx, None)
                    continue
                step = (newest - start_g) // (count - 1) if count > 1 else CLOCK // 24
                next_start = newest + step
        except (OSError, ValueError):
            pass
        finally:
            with self.cond:
                for idx in range(len(self.entries)):
                    self.infos.setdefault(idx, None)       # nothing more is coming: release the sound thread
                self.cond.notify_all()
            self._put(self.vq, None)

    # sound ---------------------------------------------------------------------------------------------------------------
    def _start_audio(self, first_pts):
        if not getattr(self, '_audio_started', False):     # (the writer also calls this, after the first picture: once is enough)
            self._audio_started = True
            self._start_audio_thread()

    def _info(self, idx):
        with self.cond:
            while idx not in self.infos and not self.stopping.is_set():
                self.cond.wait(0.2)
            return self.infos.get(idx)

    def _chain_audio(self):
        want = hf.AUDIO_CHUNK_FRAMES * 4
        held = collections.deque()                         # (pts, bytes) not yet queued
        try:
            for idx, e in enumerate(self.entries):
                proc = self._spawn('audio', e.audio_cmd(0.0)) if e.audio_early else None     # (a Plex transcode takes seconds to start)
                info = self._info(idx)
                if self.stopping.is_set():
                    return
                if info is None:
                    if proc is not None:
                        proc.kill()
                    continue
                first, start_g = info
                # this clip's start is known now, so the previous clip's held-back sound can be trimmed to end where it began
                while held:
                    pts, chunk = held.popleft()
                    if pts + hf.AUDIO_CHUNK_FRAMES * CLOCK // 48000 <= start_g + CLOCK // 50 and not self._put(self.aq, (pts, chunk)):
                        return
                if proc is None:
                    proc = self._spawn('audio', e.audio_cmd(first / float(CLOCK)))
                frames, buf = 0, bytearray()
                while not self.stopping.is_set():
                    data = proc.stdout.read(want)
                    if not data:
                        break
                    buf += data
                    self.marks.setdefault('sound', time.monotonic() - self.t0)
                    while len(buf) >= want:
                        held.append((start_g + frames * CLOCK // 48000, bytes(buf[:want])))
                        del buf[:want]
                        frames += hf.AUDIO_CHUNK_FRAMES
                        while len(held) > HOLD_CHUNKS:
                            if not self._put(self.aq, held.popleft()):
                                return
            while held and not self.stopping.is_set():
                if not self._put(self.aq, held.popleft()):
                    return
        except (OSError, ValueError):
            pass
        finally:
            self._put(self.aq, None)
