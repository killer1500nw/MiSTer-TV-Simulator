"""The set-top box: tunes the scheduled channel on the H.264 core, with a channel banner, number entry and a guide."""
import datetime as dt
import glob
import os
import random
import re
import sys
import threading
import time
from pathlib import Path

from .. import netinfo, share, streams
from ..schedule import Scheduler
from ..store import channels_from_json, items_from_catalog, load_json
from . import guide, h264feed, h264ring as hr, rumble
from .aspect import AspectBook
from .chain import ChainFeeder, Entry
from .overlay import OV_H, OV_W, Overlay, rgb
from .pad import Pad

BANNER_SECONDS = 4.0
DIGIT_WAIT = 1.6
RBF = '_Other/H264'

BLUE, DARK, MID = rgb(0, 0, 112), rgb(0, 0, 64), rgb(0, 0, 150)
WHITE, YELLOW, CYAN, SEL = rgb(255, 255, 255), rgb(255, 224, 0), rgb(96, 224, 255), rgb(0, 112, 160)
RED = rgb(150, 0, 0)
BLACK = rgb(0, 0, 0)
TUNING_MAX = 15.0            # seconds: the static never stays longer than this even if no picture arrives


class Runtime:
    """Where ffmpeg lives (the player's own folder on the card)."""

    def __init__(self, ca=None):
        found = sorted(glob.glob('/media/fat/MiSTer_90s_TV/ffmpeg-*-armhf-static/ffmpeg'))
        if not found:
            raise RuntimeError('No ffmpeg found in /media/fat/MiSTer_90s_TV (run the installer or tools/deploy_player.py).')
        self.ffmpeg = Path(found[0])
        # for https sources (a Plex plex.direct address): the CA list the installer put next to the program
        self.ca = Path(ca) if ca and os.path.isfile(ca) else Path('/etc/ssl/cert.pem')


def leave_to_menu(log):
    """Hand the screen back to the MiSTer menu (nothing else is started). Never while another core (Plex, YouTube...) has been loaded:
    that would throw the user out of it."""
    if hr.core_name() not in ('H264', 'MENU', ''):
        log('another core is loaded (%s): not touching it' % hr.core_name())
        return
    try:
        fd = os.open('/dev/MiSTer_cmd', os.O_WRONLY | getattr(os, 'O_NONBLOCK', 0))
        try:
            os.write(fd, b'load_core /media/fat/menu.rbf' + bytes([10]))
        finally:
            os.close(fd)
    except OSError as exc:
        log('Could not return to the MiSTer menu: %s' % exc)


def clock_text(sec):
    h, m = sec // 3600 % 24, sec // 60 % 60
    return '%d:%02d%s' % (h % 12 or 12, m, 'P' if h >= 12 else 'A')


def nice_title(item):
    """A short on-screen title: the show name when the episode title does not already carry it."""
    t = re.sub(r'[._]+', ' ', item.title).strip()
    show = re.sub(r'\(.*?\)|\[.*?\]|season.*$', '', item.show, flags=re.I).strip()
    first = show.split(' ')[0].lower() if show else ''
    if item.kind != 'episode' or not first or first in t.lower() or item.show.lower().startswith(('season', 'extras')):
        return t
    return '%s: %s' % (show, t)


def fit(s, n):
    return s if len(s) <= n else s[:max(0, n - 1)] + '.'


class App:
    FILES = ('channels.json', 'runtime_catalog.json', 'config.json')

    def __init__(self, folder, log):
        self.log, self.folder = log, folder
        self.channels, self.items, self.cfg, self.sched, self.aspects = [], {}, {}, None, None
        self.aspect_msg, self.aspect_until = '', 0.0
        self.stamp, self.seen_stamp, self.seen_at = None, None, 0.0
        self.reload_pending = False
        self.rt = None
        self.idx = 0
        self.foreign, self.last_core_check, self.core_checks = False, 0.0, 0
        self.menu_seconds, self.recovering = 0, False
        self.setup = False
        self.join = None                                   # the 'join another MiSTer' screen on the set-up page
        self.tuning, self.tuning_until, self.tuning_start = '', 0.0, 0.0
        self.logo_until, self.logo_cache = 0.0, {}
        self.static_frames, self.static_i = [], 0
        self.stop = self.quit = False
        self.banner_until = 0.0
        self.digits, self.digit_time = '', 0.0
        self.guide_open, self.guide_sel, self.guide_info = False, 0, False
        self.guide_at = self.guide_win = None
        self.guide_cache = {}
        self.theme = guide.DEFAULT_THEME
        self.slate = None
        self.exit_until = 0.0
        self.dirty = True
        self.last_poll = self.last_draw = 0.0
        self.end_ts = 0.0
        self.chain_on = False
        self.slot_key = None
        self.last_slot_check = 0.0
        self.last_file_check = 0.0

    def file_stamp(self):
        out = []
        for name in self.FILES:
            try:
                st = os.stat(os.path.join(self.folder, name))
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    def load_data(self):
        """(Re)read channels, catalog and config. -> False when they are missing or empty (set-up not done yet); keeps the old ones then."""
        stamp = self.file_stamp()
        try:
            cfg = streams.normalize(load_json(os.path.join(self.folder, 'config.json')))
            items = items_from_catalog(load_json(os.path.join(self.folder, 'runtime_catalog.json')))
            channels = channels_from_json(load_json(os.path.join(self.folder, 'channels.json')))
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if not channels:
            return False
        number = self.channels[self.idx].number if self.channels else None
        self.cfg, self.items, self.channels = cfg, items, channels
        self.logo_cache = {}                                  # (logos are read again from the new files)
        self.guide_cache = {}                                 # (and the guide's programme cells)
        self.sched = Scheduler(items)
        self.aspects = AspectBook(os.path.join(self.folder, 'aspects.json'), cfg.get('aspect_default', 'Fit'))
        self.idx = next((i for i, c in enumerate(channels) if c.number == number), 0)
        self.stamp = self.seen_stamp = stamp
        return True

    def studio_lines(self):
        """-> (address text, code text) to show on the TV for the web page."""
        addr = netinfo.studio_address()
        try:
            code = load_json(os.path.join(self.folder, 'pairing.json')).get('code', '')
        except (OSError, ValueError):
            code = ''
        return addr, code

    # drawing -----------------------------------------------------------------------------------------------------------------
    def span(self, ch, when):
        """-> (title text, start s, end s) of the programme that holds `when`, ads included in its span."""
        prog = self.sched.programme(ch, when)
        block = [a for a in self.sched.day(ch, when.date()) if a.slot == prog.slot]
        item = prog.item
        title = nice_title(item)
        return title, block[0].start, block[-1].end

    def draw_banner(self, c, now):
        ch = self.channels[self.idx]
        title, start, end = self.span(ch, now)
        c.rect(40, 322, 560, 112, BLUE)
        c.rect(40, 322, 560, 4, CYAN)
        head = '%02d  %s' % (ch.number, ch.name.upper())
        c.text(56, 336, fit(head, 22), YELLOW, BLUE, 3)
        c.text(56, 372, fit(title, 33), WHITE, BLUE, 2)
        c.text(56, 400, '%s - %s' % (clock_text(start), clock_text(end)), CYAN, BLUE, 2)
        t = clock_text(now.hour * 3600 + now.minute * 60)
        c.text(600 - 16 - c.text_width(t), 400, t, WHITE, BLUE, 2)

    def draw_digits(self, c):
        c.rect(430, 40, 170, 56, BLUE)
        c.text(446, 52, 'CH ' + self.digits.ljust(2, '_'), YELLOW, BLUE, 4)

    def nice_title(self, item):
        return nice_title(item)

    def read_theme(self):
        """The guide's look: what was last chosen on the TV or in Studio (guide_theme.txt), else the config, else the default."""
        names = [k for k, _ in guide.THEMES]
        try:
            with open(os.path.join(self.folder, 'guide_theme.txt'), encoding='utf-8') as f:
                t = f.read().strip()
            if t in names:
                return t
        except OSError:
            pass
        t = self.cfg.get('guide_theme')
        return t if t in names else guide.DEFAULT_THEME

    def save_theme(self, name):
        try:
            with open(os.path.join(self.folder, 'guide_theme.txt'), 'w', encoding='utf-8') as f:
                f.write(name)
        except OSError:
            pass

    def logo_for(self, ch):
        """-> (settings, BGRA bytes) of the channel's logo, or None (none set, or its file is missing or the wrong size)."""
        lg = ch.meta.get('logo')
        if not lg:
            return None
        if lg['file'] not in self.logo_cache:
            try:
                with open(os.path.join(self.folder, lg['file']), 'rb') as f:
                    data = f.read()
            except OSError:
                data = b''
            self.logo_cache[lg['file']] = data if len(data) == lg['w'] * lg['h'] * 4 else b''
        data = self.logo_cache[lg['file']]
        return (lg, data) if data else None

    def arm_logo(self):
        """A logo set to show for a short time starts its time now (a tune-in, a new programme, the info button)."""
        lg = self.channels[self.idx].meta.get('logo') if self.channels else None
        self.logo_until = time.monotonic() + lg['seconds'] if lg and lg['mode'] == 'timed' else 0.0

    def draw_logo(self, c, got, above_banner):
        """The logo in the bottom right corner (above the info banner while that is showing), inside the safe area of a CRT."""
        lg, data = got
        w, h = lg['w'], lg['h']
        x = OV_W - 48 - w
        y = (322 - 8 - h) if above_banner else (OV_H - 40 - h)
        for j in range(h):
            o = ((y + j) * c.w + x) * 4
            c.buf[o:o + w * 4] = data[j * w * 4:(j + 1) * w * 4]

    def static_frame(self):
        """A ready-made grey static picture (a handful are made once, so showing one costs a copy of the buffer, not 50 ms of work)."""
        if not self.static_frames:
            from .overlay import Canvas
            maker = Canvas()
            for _ in range(5):
                maker.noise()
                self.static_frames.append(bytes(maker.buf))
        self.static_i += 1
        return self.static_frames[self.static_i % len(self.static_frames)]

    def draw_tuning(self, c):
        c.buf[:] = self.static_frame()
        c.rect(36, 36, 8 * 3 * len(self.tuning) + 24, 44, BLACK)
        c.text(48, 44, self.tuning, YELLOW, BLACK, 3)

    def draw_aspect(self, c):
        c.rect(40, 36, 560, 64, BLUE)
        c.rect(40, 36, 560, 4, CYAN)
        head, _, rest = self.aspect_msg.partition(': ')
        c.text(56, 48, fit('SHAPE  ' + head, 33), YELLOW, BLUE, 2)
        c.text(56, 72, fit(rest, 33), WHITE, BLUE, 2)

    def draw_setup(self, c):
        addr, code = self.studio_lines()
        c.rect(0, 0, 640, 480, BLUE)
        c.rect(0, 150, 640, 4, CYAN)
        c.text(320 - c.text_width('MISTER 90S TV', 4) // 2, 60, 'MISTER 90S TV', YELLOW, BLUE, 4)
        c.text(320 - c.text_width('SIMULATOR', 4) // 2, 100, 'SIMULATOR', YELLOW, BLUE, 4)
        c.text(48, 176, '1. On a phone or computer, open:', WHITE, BLUE, 2)
        if addr:
            c.text(320 - c.text_width(addr, 2) // 2, 208, addr, CYAN, BLUE, 2)
        else:
            c.text(48, 208, 'No network: connect Wi-Fi or a cable', CYAN, BLUE, 2)
        c.text(48, 252, '2. When asked, type this code:', WHITE, BLUE, 2)
        c.text(320 - c.text_width(code or '----', 5) // 2, 286, code or '----', YELLOW, BLUE, 5)
        c.text(48, 350, '3. Add your Jellyfin or Plex server,', WHITE, BLUE, 2)
        c.text(48, 374, '   build channels, press Apply to TV.', WHITE, BLUE, 2)
        c.text(48, 408, 'Or press A to copy the channels of', YELLOW, BLUE, 2)
        c.text(48, 428, 'another MiSTer in your home.', YELLOW, BLUE, 2)
        c.text(48, 460, 'Waiting for channels...   BACK twice: exit', CYAN, BLUE, 1)

    # joining another MiSTer (set-up page only) ---------------------------------------------------------------------------------
    def start_join(self):
        self.join = {'stage': 'scan', 'found': [], 'sel': 0, 'code': [0, 0, 0, 0], 'pos': 0, 'msg': ''}
        self.dirty = True

        def work():
            try:
                found = share.scan(share.device(self.folder)['id'])
            except Exception as exc:
                found = []
                self.log('join: scan failed: %s' % exc)
            if self.join and self.join['stage'] == 'scan':
                self.join.update(stage='list', found=found, sel=0)
            self.dirty = True
        threading.Thread(target=work, daemon=True).start()

    def send_join(self):
        j = self.join
        m = j['found'][j['sel']]
        j['stage'] = 'busy'
        self.dirty = True
        code = ''.join(str(d) for d in j['code'])

        def work():
            try:
                share.join(self.folder, m['host'], m['port'], code, m['name'], m['id'])
                self.log('join: copied the channels of %s' % m['name'])
                if self.join is j:
                    j.update(stage='done')
            except share.ShareError as exc:
                if self.join is j:
                    j.update(stage='error', msg=str(exc))
            except Exception as exc:
                if self.join is j:
                    j.update(stage='error', msg='%s' % exc)
            self.dirty = True
        threading.Thread(target=work, daemon=True).start()

    def handle_join(self, a):
        j = self.join
        st = j['stage']
        if a == 'back':
            self.join = None
        elif st == 'list':
            if a in ('up', 'down') and j['found']:
                j['sel'] = (j['sel'] + (1 if a == 'down' else -1)) % len(j['found'])
            elif a == 'ok':
                if j['found']:
                    j.update(stage='code', code=[0, 0, 0, 0], pos=0)
                else:
                    self.start_join()                     # nothing found: look again
        elif st == 'code':
            if a == 'up':
                j['code'][j['pos']] = (j['code'][j['pos']] + 1) % 10
            elif a == 'down':
                j['code'][j['pos']] = (j['code'][j['pos']] - 1) % 10
            elif a == 'right':
                j['pos'] = min(3, j['pos'] + 1)
            elif a == 'left':
                j['pos'] = max(0, j['pos'] - 1)
            elif a.startswith('digit:'):
                j['code'][j['pos']] = int(a[6:])
                j['pos'] = min(3, j['pos'] + 1)
            elif a == 'ok':
                if j['pos'] < 3:
                    j['pos'] += 1
                else:
                    self.send_join()
        elif st == 'error' and a == 'ok':
            j.update(stage='code', pos=0)
        self.dirty = True

    def draw_join(self, c):
        j = self.join
        c.rect(0, 0, 640, 480, BLUE)
        c.rect(0, 100, 640, 4, CYAN)
        c.text(320 - c.text_width('JOIN ANOTHER MISTER', 3) // 2, 48, 'JOIN ANOTHER MISTER', YELLOW, BLUE, 3)
        st = j['stage']
        if st == 'scan':
            c.text(48, 200, 'Looking for other MiSTers...', WHITE, BLUE, 2)
        elif st == 'list':
            if not j['found']:
                c.text(48, 150, 'None found.', WHITE, BLUE, 2)
                c.text(48, 190, 'The other MiSTer must be on the same', CYAN, BLUE, 2)
                c.text(48, 214, 'network, with this program running.', CYAN, BLUE, 2)
                c.text(48, 300, 'A: look again    BACK: cancel', WHITE, BLUE, 2)
            else:
                for k, m in enumerate(j['found'][:7]):
                    sel = k == j['sel']
                    c.rect(40, 124 + k * 36, 560, 32, YELLOW if sel else DARK)
                    c.text(52, 132 + k * 36, fit('%s  %s' % (m['name'], m['host']), 33), BLUE if sel else WHITE, YELLOW if sel else DARK, 2)
                c.text(48, 410, 'UP/DOWN: choose   A: join   BACK: cancel', CYAN, BLUE, 1)
        elif st in ('code', 'error'):
            m = j['found'][j['sel']]
            c.text(48, 130, fit('Code shown on %s:' % m['name'], 36), WHITE, BLUE, 2)
            for k in range(4):
                x = 140 + k * 92
                c.rect(x, 200, 64, 80, YELLOW if k == j['pos'] else DARK)
                c.text(x + 4, 212, str(j['code'][k]), BLUE if k == j['pos'] else WHITE, YELLOW if k == j['pos'] else DARK, 7)
            if st == 'error':
                c.text(48, 316, fit(j['msg'], 36), rgb(255, 150, 150), BLUE, 2)
            c.text(48, 410, 'UP/DOWN: digit  LEFT/RIGHT: move  A: join', CYAN, BLUE, 1)
        elif st == 'busy':
            c.text(48, 200, 'Copying the channels...', WHITE, BLUE, 2)
        elif st == 'done':
            c.text(48, 200, 'Done. Starting the channels...', WHITE, BLUE, 2)

    def draw_slate(self, c):
        title, sub = self.slate
        c.rect(0, 0, 640, 480, BLUE)
        c.rect(0, 200, 640, 4, CYAN)
        c.text(320 - c.text_width(fit(title, 24), 3) // 2, 214, fit(title, 24), YELLOW, BLUE, 3)
        c.text(320 - c.text_width(fit(sub, 36)) // 2, 262, fit(sub, 36), WHITE, BLUE, 2)

    def render(self):
        c, now = self.ov.canvas, dt.datetime.now()
        mono = time.monotonic()
        if self.banner_until and mono > self.banner_until:
            self.banner_until = 0.0
        if self.aspect_until and mono >= self.aspect_until:
            self.aspect_until = 0.0
        if self.logo_until and mono >= self.logo_until:
            self.logo_until = 0.0
        if self.digits and mono - self.digit_time > DIGIT_WAIT:
            self.tune_digits()
        if not self.tuning:
            c.clear()                                     # (the static replaces the whole canvas anyway)
        shown = False
        if self.tuning:
            self.draw_tuning(c)
            shown = True
        if self.slate:
            self.draw_slate(c)
            shown = True
        if self.setup:
            if self.join:
                self.draw_join(c)
            else:
                self.draw_setup(c)
            shown = True
        elif self.guide_open:
            guide.look(self.theme).draw(self, c, now)
            if self.guide_info:
                guide.draw_info(self, c, now)
            shown = True
        elif self.banner_until:
            self.draw_banner(c, now)
            shown = True
        if self.digits:
            self.draw_digits(c)
            shown = True
        if not (self.tuning or self.setup or self.guide_open or self.slate) and self.channels:
            got = self.logo_for(self.channels[self.idx])
            if got and (got[0]['mode'] == 'always' or mono < self.logo_until):
                self.draw_logo(c, got, bool(self.banner_until))
                shown = True
        if mono < self.aspect_until:
            self.draw_aspect(c)
            shown = True
        if mono < self.exit_until:
            c.rect(120, 420, 400, 36, RED)
            c.text(136, 428, 'PRESS BACK AGAIN TO EXIT', WHITE, RED, 2)
            shown = True
        if shown:
            if not self.ov.show():
                return False                        # the core has not taken the last page yet: draw again soon
        elif self.ov.shown is not None:
            self.ov.hide()
        return True

    # input -------------------------------------------------------------------------------------------------------------------
    def show_banner(self):
        self.banner_until = time.monotonic() + BANNER_SECONDS
        self.arm_logo()
        self.dirty = True

    def change(self, delta=0, number=None):
        if number is not None:
            idx = next((i for i, c in enumerate(self.channels) if c.number == number), None)
            if idx is None:
                return
        else:
            idx = (self.idx + delta) % len(self.channels)
        if idx != self.idx:
            self.idx = idx
            self.stop = True
        self.slate = None
        self.show_banner()

    def tune_digits(self):
        if self.digits:
            self.change(number=int(self.digits))
        self.digits = ''
        self.dirty = True

    def handle(self, a):
        mono = time.monotonic()
        if self.setup:                                  # only BACK works until there are channels (and A: join another MiSTer)
            if self.join:
                self.handle_join(a)
                return
            if a == 'ok':
                self.start_join()
                return
            if a == 'back':
                if mono < self.exit_until:
                    self.quit = self.stop = True
                else:
                    self.exit_until = mono + 2.5
                    self.dirty = True
            return
        if a.startswith('digit:'):
            if len(self.digits) < 2:
                self.digits += a[6:]
            self.digit_time = mono
            self.dirty = True
            return
        if self.digits and a == 'ok':
            self.tune_digits()
            return
        if self.guide_open:
            look = guide.look(self.theme)
            if a == 'info':                                     # Y / I: the details of the highlighted programme
                self.guide_info = not self.guide_info
            elif self.guide_info and a in ('back', 'guide'):
                self.guide_info = False
            elif a in ('up', 'down', 'left', 'right', 'pgup', 'pgdn'):
                self.guide_info = False
                guide.move(self, a, look.rows, look.cols)
            elif a == 'ok':
                self.guide_open = False
                self.change(number=self.channels[self.guide_sel].number)
            elif a == 'menu':                                   # Start / M: the next look, remembered
                self.theme = guide.next_theme(self.theme)
                self.save_theme(self.theme)
            elif a in ('back', 'guide'):
                self.guide_open = False
            self.dirty = True
            return
        if a in ('up', 'pgup'):
            self.change(+1)
        elif a in ('down', 'pgdn'):
            self.change(-1)
        elif a == 'ok':
            if self.banner_until:
                self.banner_until = 0.0
            else:
                self.show_banner()
            self.dirty = True
        elif a in ('menu', 'right', 'info'):
            self.cycle_aspect(+1)
        elif a == 'left':
            self.cycle_aspect(-1)
        elif a == 'guide':
            self.theme = self.read_theme()
            guide.open_guide(self, dt.datetime.now())
            self.guide_open = True
            self.dirty = True
        elif a == 'back':
            if mono < self.exit_until:
                self.quit = self.stop = True
            else:
                self.exit_until = mono + 2.5
                self.dirty = True

    def cycle_aspect(self, step):
        """Next / previous picture shape for what is on now; the picture restarts (about a second) so it shows at once."""
        ch = self.channels[self.idx]
        airing, _ = self.sched.now(ch, dt.datetime.now())
        if airing.item.kind == 'filler':
            return
        self.aspects.cycle(airing.item, step)
        name, text = self.aspects.describe(airing.item)
        self.aspect_msg, self.aspect_until = '%s: %s' % (name.upper(), text), time.monotonic() + 3.5
        self.stop = True
        self.dirty = True

    def service(self):
        """Called while waiting on video: read the remote, redraw, and say whether to stop the current stream."""
        mono = time.monotonic()
        if mono - self.last_poll >= 0.04:
            self.last_poll = mono
            for a in self.pad.poll():
                self.handle(a)
        due = ((self.banner_until and mono >= self.banner_until) or (self.aspect_until and mono >= self.aspect_until)
               or (self.logo_until and mono >= self.logo_until) or (self.digits and mono - self.digit_time > DIGIT_WAIT)
               or (self.exit_until and mono >= self.exit_until))
        if (self.dirty or due) and mono - self.last_draw >= (0.2 if self.tuning else 0.12):
            self.last_draw = mono
            if self.exit_until and mono >= self.exit_until:
                self.exit_until = 0.0
            self.dirty = not self.render()           # False from render: the core has not taken the last page yet
        if self.tuning:
            if mono > self.tuning_until or self.ring.status()['pictures_seen'] >= 2:
                marks = getattr(getattr(self, 'feeder', None), 'marks', {})
                self.log('  picture after %.1f s (first video data %.1f s, first sound data %.1f s)' % (
                    mono - self.tuning_start, marks.get('video', -1), marks.get('sound', -1)))
                self.tuning = ''
                self.arm_logo()
            self.dirty = True                              # the static is redrawn every time
        if mono - self.last_core_check >= 1.0:
            self.last_core_check = mono
            self.core_checks += 1
            self.menu_seconds = self.menu_seconds + 1 if hr.core_name() == 'MENU' and not self.recovering else 0
            if self.core_taken_over(self.core_checks % 3 == 0) or self.menu_seconds >= 4:
                self.foreign = self.quit = self.stop = True
                self.log('the MiSTer left our core (now %s): stopping without touching it' % (hr.core_name() or '?'))
        if mono - self.last_file_check >= 2.0 and not self.setup:
            self.last_file_check = mono
            stamp = self.file_stamp()
            if stamp != self.seen_stamp:
                self.seen_stamp, self.seen_at = stamp, mono                # changing: wait until it has been still for a moment
            elif stamp != self.stamp and mono - self.seen_at >= 1.5:
                self.reload_pending = self.stop = True
        if self.chain_on and mono - self.last_slot_check >= 1.0:
            self.last_slot_check = mono                  # a new programme started (by the clock): show its banner
            ch = self.channels[self.idx]
            key = self.programme_key(ch)
            if key != self.slot_key:
                self.slot_key = key
                if not self.sched.is_ad(ch, self.sched.programme(ch, dt.datetime.now()).item):
                    self.show_banner()
        return self.stop or self.quit or time.time() >= self.end_ts

    def audio_command(self, src, start_s):
        """The feeder's audio command, but with -ss as an absolute time stamp: the feeder passes the video's first time stamp, and
        ffmpeg would otherwise add the stream's own start time (Jellyfin's transcodes start at about 1.4 s) on top, so the sound
        would come from about 1.4 s later than the picture."""
        cmd = h264feed.audio_pcm_command(self.rt, src, start_s)
        if '-ss' in cmd:
            cmd[cmd.index('-ss'):cmd.index('-ss')] = ['-seek_timestamp', '1']
        return cmd

    # playing -----------------------------------------------------------------------------------------------------------------
    def clip(self, item, offset, session):
        """-> an Entry (ffmpeg command builders) for one library item."""
        st = streams.stream(self.cfg, item, offset, session)
        vsrc, asrc = {'url': st.video_url, 'headers': st.headers}, {'url': st.audio_url, 'headers': st.headers}

        def vcmd(start_s):
            if st.prepare:
                st.prepare('v')
            return h264feed.video_copy_command(self.rt, vsrc, start_s)

        def acmd(start_s):
            if st.prepare:
                st.prepare('a')
            return self.audio_command(asrc, start_s if st.audio_seekable else 0.0)
        return Entry(item.title, vcmd, acmd, st.seek_s, crop=self.aspects.steps(item), audio_early=not st.audio_seekable)

    def chain_entries(self, ch, now, off, horizon=75 * 60):
        """The clips from now on (the current one from `off`, then ads and programmes in schedule order) for about `horizon` seconds.
        Station idents have no media, so they are left out: the next clip simply follows."""
        entries, total, first = [], 0, True
        sec = now.hour * 3600 + now.minute * 60 + now.second
        date = now.date()
        for _ in range(3):
            for a in self.sched.day(ch, date):
                if date == now.date() and a.end <= sec:
                    continue
                if a.item.kind == 'filler' or a.item.duration <= 0:
                    continue
                o = off if first else 0
                first = False
                entries.append(self.clip(a.item, o, '%032x' % random.getrandbits(128)))
                total += a.item.duration - o
                if total >= horizon:
                    return entries
            date += dt.timedelta(days=1)
        return entries

    def play(self, ch, airing, off):
        item = airing.item
        self.ring.new_session()
        try:
            self.ring.request_settings(analog_aspect=2)      # the core stays on Letterbox; the crop modes trim the stream itself
        except hr.RingError:
            pass
        self.chain_on = bool(self.cfg.get('chain', True))
        self.tuning, self.tuning_start = 'CH %02d' % ch.number, time.monotonic()
        self.tuning_until = self.tuning_start + TUNING_MAX
        if self.chain_on:
            entries = self.chain_entries(ch, dt.datetime.now(), off)
            feeder = ChainFeeder(self.ring, entries, log=self.log)
            self.end_ts = time.time() + 3 * 86400            # the chain ends by itself; a channel change or BACK stops it
            self.slot_key = self.programme_key(ch)
            self.log('ch %d: %s (%s, %s) at %ds, then %d more clips' % (
                ch.number, item.title, item.kind, 'direct' if item.direct_ok else 'transcode', off, len(entries) - 1))
        else:
            e = self.clip(item, off, '%032x' % random.getrandbits(128))
            feeder = h264feed.Feeder(self.ring, e.video_cmd, e.audio_cmd, log=self.log, duration_s=item.duration)
            self.log('ch %d: %s (%s, %s) at %ds' % (ch.number, item.title, item.kind, 'direct' if item.direct_ok else 'transcode', off))
        feeder.start(0.0 if self.chain_on else e.seek_s)
        self.feeder = feeder
        result = feeder.run(stop=self.service, tick=self.service)
        self.chain_on = False
        self.log('  -> %s (first picture time %s s; lead min/mean ms %s; written %s)' % (
            result, None if feeder.first_pts is None else round(feeder.first_pts / 90000.0, 2), feeder.take_lead(), feeder.stats))

    def programme_key(self, ch):
        prog = self.sched.programme(ch, dt.datetime.now())
        return (ch.number, prog.slot, prog.start, dt.date.today())

    def wait_setup(self):
        self.setup = True
        self.dirty = True
        self.log('no channels yet: showing the set-up screen')
        last = 0.0
        while not self.quit:
            self.service()
            if time.monotonic() - last > 1.5:
                last = time.monotonic()
                if self.load_data():
                    break
            time.sleep(0.05)
        self.setup = False
        self.join = None
        self.dirty = True
        self.log('channels found: %d' % len(self.channels))

    def wait_slate(self, title, sub, until_ts):
        self.slate = (title, sub)
        self.dirty = True
        self.end_ts = until_ts
        while not self.service():
            time.sleep(0.03)
        self.slate = None
        self.dirty = True

    def open_core(self):
        hr.launch_core(RBF)
        self.ring, self.mem = hr.open_devmem()
        end = time.monotonic() + 15.0
        while True:                                # a core that has only just loaded takes a moment to start answering
            try:
                self.ring.alive(10.0)
                break
            except hr.RingError:
                if time.monotonic() > end:
                    raise
                time.sleep(0.5)
        self.ring.new_session()                    # the core shows overlays only inside a session, even with no video yet
        self.ov = Overlay(self.ring, self.log)
        self.ov.hide()
        self.pad = Pad(self.ring)

    def core_taken_over(self, deep):
        """True when the MiSTer is now running some other core (Plex, YouTube...), so this player must stop and leave it alone. Cheap check
        every second (the core's name); `deep` also confirms, when the starter launched us, that the H.264 core was loaded through our menu
        entry and not another program's entry for the same core."""
        name = hr.core_name()
        if name not in ('H264', 'MENU', ''):
            return True
        if deep and name == 'H264' and os.environ.get('C90_GUARD'):
            from .. import daemon
            return not daemon.loaded_by_our_entry(daemon.processes())
        return False

    def close_core(self):
        if self.foreign:                                   # the core now belongs to another program: write nothing to it
            try:
                self.mem.close()
            except Exception:
                pass
            return
        for step in (lambda: self.ov.close(), lambda: self.ring.close(), lambda: self.ring.release(), lambda: self.mem.close()):
            try:
                step()
            except Exception:
                pass

    def recover_core(self):
        """The core stopped answering (it can wedge under load): load the menu, load the core again and carry on."""
        self.log('the core does not answer: reloading it')
        self.recovering = True                             # (the menu is expected for a moment: that is not the user leaving)
        try:
            self.close_core()
            leave_to_menu(self.log)
            end = time.monotonic() + 12.0
            while time.monotonic() < end and hr.core_name() == 'H264':      # wait until the menu has really replaced it
                time.sleep(0.3)
            time.sleep(1.0)
            self.open_core()
        finally:
            self.recovering, self.menu_seconds = False, 0
        self.dirty = True

    def run(self):
        self.rt = Runtime(os.path.join(self.folder, 'cacert.pem'))
        failures, recoveries = 0, 0
        self.open_core()
        mute = rumble.Mute()
        mute.start()                                   # pads do not rumble while the TV is on
        try:
            self.static_frame()                        # make the static pictures now, not in the middle of the first channel change
            if not self.load_data():
                self.wait_setup()                      # nothing to play yet: show how to set it up from a browser
            self.show_banner()
            while not self.quit:
                self.stop = False
                if self.reload_pending:
                    self.reload_pending = False
                    if self.load_data():
                        self.log('channels reloaded: %d channels' % len(self.channels))
                    else:
                        self.log('the new channel files could not be read; keeping the old ones')
                        self.stamp = self.seen_stamp
                    self.show_banner()
                ch = self.channels[self.idx]
                now = dt.datetime.now()
                airing, off = self.sched.now(ch, now)
                midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
                self.end_ts = (midnight + dt.timedelta(seconds=airing.end)).timestamp()
                item = airing.item
                if not self.sched.is_ad(ch, item) and off < 8:
                    self.show_banner()
                try:
                    if item.kind == 'filler' or off >= item.duration - 2:
                        self.wait_slate(ch.name.upper(), 'Back in a moment' if item.kind == 'filler' else '', self.end_ts)
                    else:
                        self.play(ch, airing, off)
                    failures = 0
                except (hr.RingError, RuntimeError, OSError) as exc:
                    failures += 1
                    self.log('  FAILED: %s' % exc)
                    if isinstance(exc, hr.RingError):
                        recoveries += 1
                        if recoveries > 4:
                            raise
                        self.recover_core()                # (a few times at most per run, then give up and leave to the menu)
                        failures = 0
                        continue
                    if failures >= 5:
                        raise
                    self.wait_slate('NO SIGNAL', fit(item.title, 36), time.time() + 4)
        finally:
            mute.stop()
            self.close_core()


def make_logger(path):
    key = re.compile(r'api_key=[0-9A-Za-z]+')
    try:
        fh = open(path, 'a', encoding='utf-8')
    except OSError:
        fh = None

    def log(msg):
        line = '%s %s' % (time.strftime('%H:%M:%S'), key.sub('api_key=***', str(msg)))
        print(line, flush=True)
        if fh:
            fh.write(line + '\n')
            fh.flush()
    return log


def main(argv=None):
    folder = (argv or sys.argv[1:] or ['/media/fat/Scripts/.config/MiSTer_90s_TV'])[0]
    log = make_logger(os.path.join(folder, 'log.txt'))
    log('MiSTer 90s TV Simulator starting')
    try:
        import faulthandler
        import signal
        faulthandler.register(signal.SIGUSR1, all_threads=True)       # kill -USR1 <pid>: where is it stuck? (written to the console output)
    except (ImportError, AttributeError, ValueError):
        pass
    code = 0
    app = None
    try:
        app = App(folder, log)
        app.run()
    except KeyboardInterrupt:
        log('Stopped.')
    except Exception as exc:                      # the log is how a failure on the MiSTer gets diagnosed
        import traceback
        log('FATAL: %s' % exc)
        log(traceback.format_exc())
        code = 1
    if not (app and app.foreign):
        leave_to_menu(log)
    return code
