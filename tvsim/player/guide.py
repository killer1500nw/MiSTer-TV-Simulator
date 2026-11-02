"""The TV guide, with several looks ("themes") that share one set of programme cells and one way of moving around.

    classic    the original two-column list
    satellite  a full-screen grid on a blue gradient (in the manner of UK / Australian satellite boxes)
    cable      an information panel over the live picture and a grid with channel labels (in the manner of US cable boxes)
    modern     a dark translucent panel over the live picture, now and next for each channel with a progress bar

The looks are only inspired by those boxes: no logos, names or artwork of any provider are used.
Everything is drawn into the 640x480 overlay canvas with the 8x8 font; the core blends the overlay with the picture (it understands
partial transparency), which is what lets `cable` and `modern` leave the live picture visible.
"""
import datetime as dt
import re

THEMES = [('satellite', 'Satellite (UK / Australia style)'), ('cable', 'Cable (US style)'), ('modern', 'Modern'), ('classic', 'Classic')]
DEFAULT_THEME = 'satellite'
HALF_HOUR = dt.timedelta(minutes=30)


def rgb(r, g, b, a=255):
    return bytes((b, g, r, a))


# ---- the cells: one per programme, ads included in its span --------------------------------------------------------------------
class Cell:
    __slots__ = ('start', 'end', 'title', 'item', 'ad_free')

    def __init__(self, start, end, title, item):
        self.start, self.end, self.title, self.item = start, end, title, item


def guide_title(app, item):
    """What a guide cell calls a programme: an episode by its show ("Captain Comet": there is no room for the episode title), a film by its
    title. A show whose name is only a folder name ("Season 2 1993") falls back to the full title."""
    show = re.sub(r'\(.*?\)|\[.*?\]', '', item.show or '').strip()
    if item.kind == 'episode' and show and not re.match(r'(season|series|extras|specials)\b', show, re.I):
        return show
    return app.nice_title(item)


def day_cells(app, ch, day):
    """[Cell] tiling `day` for one channel (cached for the day: building them walks the whole schedule)."""
    cache = app.guide_cache
    key = (ch.number, day)
    if key not in cache:
        if len(cache) > 400:
            cache.clear()
        airings = app.sched.day(ch, day)
        base = dt.datetime.combine(day, dt.time())
        slots = {}
        for a in airings:
            e = slots.setdefault(a.slot, [a, a.start, a.end])
            e[2] = max(e[2], a.end)
        cells = []
        for a, s, e in slots.values():
            title = 'OFF AIR' if a.item.kind == 'filler' else guide_title(app, a.item)
            cells.append(Cell(base + dt.timedelta(seconds=s), base + dt.timedelta(seconds=e), title, a.item))
        cells.sort(key=lambda c: c.start)
        cache[key] = cells
    return cache[key]


def cell_at(app, ch, when):
    for cell in day_cells(app, ch, when.date()):
        if cell.start <= when < cell.end:
            return cell
    cells = day_cells(app, ch, when.date())
    return cells[-1] if cells else None


def cells_between(app, ch, t0, t1):
    out, day = [], t0.date()
    while dt.datetime.combine(day, dt.time()) < t1:
        out += [c for c in day_cells(app, ch, day) if c.end > t0 and c.start < t1]
        day += dt.timedelta(days=1)
    return out


def floor30(t):
    return t.replace(minute=t.minute - t.minute % 30, second=0, microsecond=0)


# ---- moving around -------------------------------------------------------------------------------------------------------------
def open_guide(app, now):
    app.guide_sel = app.idx
    app.guide_at = now
    app.guide_win = floor30(now)
    app.guide_info = False


def keep_visible(app, span):
    if app.guide_at < app.guide_win:
        app.guide_win = floor30(app.guide_at)
    elif app.guide_at >= app.guide_win + span:
        app.guide_win = floor30(app.guide_at)


def move(app, action, rows, cols):
    """Apply a remote action to the guide cursor (channel row, time)."""
    n = len(app.channels)
    span = HALF_HOUR * cols
    if action == 'up':
        app.guide_sel = (app.guide_sel - 1) % n
    elif action == 'down':
        app.guide_sel = (app.guide_sel + 1) % n
    elif action == 'pgup':
        app.guide_sel = max(0, app.guide_sel - rows)
    elif action == 'pgdn':
        app.guide_sel = min(n - 1, app.guide_sel + rows)
    elif action in ('left', 'right'):
        ch = app.channels[app.guide_sel]
        cell = cell_at(app, ch, app.guide_at)
        if cell:
            target = cell.end if action == 'right' else cell.start - dt.timedelta(seconds=1)
            nxt = cell_at(app, ch, target)
            if nxt:
                app.guide_at = max(nxt.start, floor30(dt.datetime.now())) if action == 'left' else nxt.start
    keep_visible(app, span)


# ---- small drawing helpers -------------------------------------------------------------------------------------------------------
def fit(s, chars):
    """Cut to `chars` characters, ending in '..' when it was longer."""
    return s if len(s) <= chars else (s[:max(0, chars - 2)].rstrip() + '..' if chars > 2 else s[:chars])


def wrap_words(text, chars):
    """Lines of at most `chars` characters that break only between words; None when a single word is longer than a line."""
    rows, line = [], ''
    for word in text.split():
        if len(word) > chars:
            return None
        if line and len(line) + 1 + len(word) > chars:
            rows.append(line)
            line = word
        else:
            line = (line + ' ' + word).strip()
    rows.append(line)
    return rows


def put(c, x, cy, width, text, fg, bg, scale=2, lines=1, shrink=False):
    """Draw `text` centred on height `cy` inside `width` pixels. On one line when it fits; else (if `lines` is 2) wrapped between
    words onto two lines at the same size; else wrapped onto up to three small lines; a word is never split. Only when nothing fits
    is the end cut with '..'. -> the number of characters drawn."""
    chars = max(1, width // (8 * scale))
    if len(text) <= chars:
        c.text(x, cy - 4 * scale, text, fg, bg, scale)
        return len(text)
    rows = wrap_words(text, chars) if lines == 2 else None
    if rows and len(rows) <= 2:
        for k, row in enumerate(rows):
            c.text(x, cy - 4 * scale + (-9 + 18 * k if len(rows) == 2 else 0), row, fg, bg, scale)
        return len(text)
    if scale == 2 and (lines == 2 or shrink):
        small = width // 8
        if len(text) <= small:
            c.text(x, cy - 4, text, fg, bg, 1)
            return len(text)
        rows = wrap_words(text, small) if lines == 2 else None
        if rows and len(rows) <= 3:
            top = cy - 4 * len(rows) - (len(rows) - 1)
            for k, row in enumerate(rows):
                c.text(x, top + 9 * k, row, fg, bg, 1)
            return len(text)
    if lines == 2 and len(text) > chars:
        rows = wrap_words(text, chars)
        first, second = (text[:chars], fit(text[chars:], chars)) if not rows else (rows[0], fit(' '.join(rows[1:]), chars))
        c.text(x, cy - 13, first, fg, bg, scale)
        c.text(x, cy + 5, second, fg, bg, scale)
        return len(first) + len(second)
    shown = fit(text, chars)
    c.text(x, cy - 4 * scale, shown, fg, bg, scale)
    return len(shown)


def clock12(t, dots=False):
    h = t.hour % 12 or 12
    suffix = 'pm' if t.hour >= 12 else 'am'
    return '%d%s%02d%s' % (h, '.' if dots else ':', t.minute, suffix)


def triangle(c, x, y, size, direction, color):
    """A small solid triangle (the font has no arrows): direction 'up', 'down', 'left' or 'right'."""
    for i in range(size):
        if direction in ('up', 'down'):
            k = i if direction == 'up' else size - 1 - i
            c.rect(x + size - 1 - k, y + i, 2 * k + 1, 1, color)
        else:
            k = i if direction == 'left' else size - 1 - i
            c.rect(x + i, y + size - 1 - k, 1, 2 * k + 1, color)


def gradient(c, x, y, w, h, top, bottom):
    for j in range(h):
        t = j / max(1, h - 1)
        c.rect(x, y + j, w, 1, bytes(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + b'\xff')


def gradient_at(top, bottom, y, h=480):
    t = y / max(1, h - 1)
    return bytes(int(top[i] + (bottom[i] - top[i]) * t) for i in (2, 1, 0)) + b'\xff'


def pill(c, x, y, w, h, color):
    """A rectangle with its corners clipped, as a cheap rounded box."""
    c.rect(x + 2, y, w - 4, h, color)
    c.rect(x, y + 2, w, h - 4, color)
    c.rect(x + 1, y + 1, w - 2, h - 2, color)


def cell_box(app, c, cell, x, y, w, h, bg, fg, selected_bg=None, selected_fg=None, scale=2, cont_mark=False, win=None):
    """One programme cell, text clipped to its width (a '<' when asked and it began before the window)."""
    sel = selected_bg is not None
    c.rect(x, y, w, h, selected_bg if sel else bg)
    if w >= 40:
        title = cell.title
        if cont_mark and win is not None and cell.start < win:
            title = '<' + title
        put(c, x + 5, y + h // 2, w - 10, title, selected_fg if sel else fg, selected_bg if sel else bg, scale, 2 if h >= 38 else 1)


def cls_title(app, cell):
    """The full title of a cell's programme: "Show: Episode title" for an episode."""
    return app.nice_title(cell.item) if cell.item.kind != 'filler' else cell.title


def selected_cell(app, now):
    ch = app.channels[app.guide_sel]
    return ch, cell_at(app, ch, app.guide_at)


# ---- the looks -------------------------------------------------------------------------------------------------------------------
class Satellite:
    cols, rows = 3, 6
    BG_TOP, BG_BOT = (22, 54, 150), (8, 22, 78)
    PANEL, PANEL2, CHAN = rgb(30, 62, 170), rgb(38, 76, 190), rgb(24, 52, 150)
    YELLOW, WHITE, DARK = rgb(255, 204, 40), rgb(255, 255, 255), rgb(10, 20, 60)
    TIME = rgb(150, 205, 255)

    @classmethod
    def draw(cls, app, c, now):
        n = len(app.channels)
        gradient(c, 0, 0, 640, 480, cls.BG_TOP, cls.BG_BOT)
        c.text(30, 28, 'ALL CHANNELS', cls.YELLOW, gradient_at(cls.BG_TOP, cls.BG_BOT, 36), 3)
        stamp = '%s %s %d' % (clock12(now, True), now.strftime('%a'), now.day)
        c.text(590 - c.text_width(stamp), 32, stamp, cls.YELLOW, gradient_at(cls.BG_TOP, cls.BG_BOT, 40), 2)
        x0, lw, cw = 30, 180, 126                       # left edge, channel column, one half hour
        gx = x0 + lw + 4
        win = app.guide_win
        y = 66
        today = now.date()
        c.rect(x0, y, lw, 24, cls.PANEL)
        day = 'TODAY' if win.date() == today else win.strftime('%a %d').upper()
        triangle(c, x0 + 8, y + 8, 9, 'up', cls.WHITE)
        c.text(x0 + 24, y + 4, day, cls.WHITE, cls.PANEL, 2)
        for k in range(cls.cols):
            when = win + HALF_HOUR * k
            c.rect(gx + k * cw, y, cw - 3, 24, cls.PANEL)
            c.text(gx + k * cw + 6, y + 4, clock12(when, True), cls.WHITE, cls.PANEL, 2)
        triangle(c, gx + cls.cols * cw - 16, y + 7, 10, 'right', cls.YELLOW)
        top = max(0, min(app.guide_sel - cls.rows // 2, n - cls.rows))
        rh = 46
        sel_ch, sel_cell = selected_cell(app, now)
        for r in range(min(cls.rows, n)):
            i = top + r
            ch = app.channels[i]
            ry = 94 + r * rh
            row_sel = i == app.guide_sel
            c.rect(x0, ry, lw, rh - 3, cls.YELLOW if row_sel else cls.CHAN)
            put(c, x0 + 6, ry + (rh - 3) // 2, lw - 12, '%d %s' % (ch.number, ch.name), cls.DARK if row_sel else cls.WHITE,
                cls.YELLOW if row_sel else cls.CHAN, 2, 2)
            end = win + HALF_HOUR * cls.cols
            for cell in cells_between(app, ch, win, end):
                cs, ce = max(cell.start, win), min(cell.end, end)
                cx = gx + int((cs - win) / HALF_HOUR * cw)
                cwid = int((ce - cs) / HALF_HOUR * cw) - 3
                if cwid < 12:
                    continue
                chosen = row_sel and sel_cell is cell
                cell_box(app, c, cell, cx, ry, cwid, rh - 3, cls.PANEL2 if (r + cell.start.minute // 30) % 2 else cls.PANEL, cls.WHITE,
                         cls.YELLOW if chosen else None, cls.DARK, win=win)
        iy = 94 + cls.rows * rh + 2                      # the highlighted programme, named in full
        c.rect(x0, iy, 560, 28, cls.PANEL2)
        if sel_cell:
            full = '%s  %s' % (sel_cell.title if sel_cell.item.kind != 'episode' else cls_title(app, sel_cell), '')
            put(c, x0 + 8, iy + 14, 336, full.strip(), cls.YELLOW, cls.PANEL2, shrink=True)
            put(c, x0 + 348, iy + 14, 208, '%s-%s' % (clock12(sel_cell.start, True), clock12(sel_cell.end, True)), cls.WHITE, cls.PANEL2)
        ly = iy + 32
        c.rect(x0, ly, 560, 24, cls.CHAN)
        for k, (color, text) in enumerate(((rgb(220, 60, 60), 'L Page Up'), (rgb(70, 190, 90), 'R Page Down'), (rgb(255, 204, 40), 'A Watch'),
                                           (rgb(80, 150, 255), 'Y Info  Start Look'))):
            px = x0 + 10 + k * 140
            c.rect(px, ly + 8, 8, 8, color)
            c.text(px + 14, ly + 8, text, cls.WHITE, cls.CHAN, 1)
        addr, code = app.studio_lines()
        if addr:
            c.text(x0, 456, fit('Edit channels: %s  code %s' % (addr, code or '----'), 70), cls.TIME, gradient_at(cls.BG_TOP, cls.BG_BOT, 460), 1)


class Cable:
    cols, rows = 3, 4
    BG, HEAD = rgb(8, 24, 92), rgb(16, 44, 140, 235)
    LABEL, LABEL_SEL = rgb(120, 170, 235), rgb(255, 238, 120)
    CELLS = (rgb(20, 60, 150), rgb(70, 36, 130), rgb(20, 110, 150))
    SEL, WHITE, DARK, YELLOW = rgb(255, 240, 140), rgb(255, 255, 255), rgb(10, 20, 60), rgb(255, 224, 80)
    STRIP = rgb(236, 236, 244)

    @classmethod
    def draw(cls, app, c, now):
        n = len(app.channels)
        ch, cell = selected_cell(app, now)
        # the information panel: the top right stays clear so the live picture shows through
        c.rect(24, 24, 300, 168, cls.HEAD)
        c.text(36, 32, 'TV LISTINGS', cls.WHITE, cls.HEAD, 2)
        c.text(36, 52, clock12(now), cls.YELLOW, cls.HEAD, 2)
        if cell:
            full = cls_title(app, cell)
            if len(full) <= 17:
                c.text(36, 80, full, cls.YELLOW, cls.HEAD, 2)
            else:
                cut = full[:18].rfind(' ')
                first, rest = (full[:cut], full[cut + 1:]) if cut > 4 else (full[:17], full[17:])
                c.text(36, 72, first, cls.YELLOW, cls.HEAD, 2)
                c.text(36, 90, fit(rest, 17), cls.YELLOW, cls.HEAD, 2)
            c.text(36, 110, '%s-%s' % (clock12(cell.start), clock12(cell.end)), cls.WHITE, cls.HEAD, 2)
            label = fit('CH %d  %s' % (ch.number, ch.name.upper()), 36)
            c.text(36, 132, label, cls.WHITE, cls.HEAD, 1)
            mins = max(1, int((cell.end - cell.start).total_seconds() // 60))
            when = 'On now' if cell.start <= now < cell.end else ('Starts in %d min' % int((cell.start - now).total_seconds() // 60)
                                                                  if cell.start > now else 'Ended')
            c.text(36, 146, fit('%s - %d min' % (when, mins), 36), cls.WHITE, cls.HEAD, 1)
            if cell.item.kind == 'episode' and cell.item.show:
                c.text(36, 158, fit('S%02dE%02d  %s' % (cell.item.season, cell.item.episode, cell.item.show), 36), cls.WHITE, cls.HEAD, 1)
            c.text(36, 176, 'A watch  Y info  Start look', rgb(150, 205, 255), cls.HEAD, 1)
        # the grid
        win = app.guide_win
        gy, lw, cw, rh = 204, 140, 148, 48
        c.rect(24, gy, 592, 26, cls.HEAD)
        c.text(32, gy + 6, 'Today' if win.date() == now.date() else win.strftime('%a'), cls.WHITE, cls.HEAD, 2)
        gx = 24 + lw + 4
        for k in range(cls.cols):
            when = win + HALF_HOUR * k
            c.text(gx + k * cw + 8, gy + 6, clock12(when).replace('am', 'a').replace('pm', 'p'), cls.WHITE, cls.HEAD, 2)
            c.rect(gx + k * cw - 3, gy, 2, 26, cls.BG)
        top = max(0, min(app.guide_sel - cls.rows // 2, n - cls.rows))
        for r in range(min(cls.rows, n)):
            i = top + r
            rc = app.channels[i]
            ry = gy + 30 + r * rh
            row_sel = i == app.guide_sel
            bg = cls.LABEL_SEL if row_sel else cls.LABEL
            c.rect(24, ry, lw, rh - 3, bg)
            c.text(30, ry + 2, 'CH %d' % rc.number, cls.DARK, bg, 1)
            put(c, 30, ry + 24, lw - 12, rc.name.upper(), cls.DARK, bg, 2, 2)       # the whole name, over two lines
            end = win + HALF_HOUR * cls.cols
            for k, cc in enumerate(cells_between(app, rc, win, end)):
                cs, ce = max(cc.start, win), min(cc.end, end)
                cx = gx + int((cs - win) / HALF_HOUR * cw)
                cwid = int((ce - cs) / HALF_HOUR * cw) - 3
                if cwid < 12:
                    continue
                chosen = row_sel and cell is cc
                color = cls.CELLS[(0 if cc.item.kind == 'movie' else 1 + cc.start.hour % 2)]
                two = cc.title if len(cc.title) <= (cwid - 10) // 16 else None
                c.rect(cx, ry, cwid, rh - 3, cls.SEL if chosen else color)
                chars = (cwid - 10) // 16
                if chars >= 3:
                    words, line1, line2 = cc.title, '', ''
                    cut = words[:chars + 1].rfind(' ')
                    if len(words) <= chars or cut <= 0:
                        line1 = fit(words, chars)
                    else:
                        line1, line2 = words[:cut], fit(words[cut + 1:], chars)
                    ink = cls.DARK if chosen else cls.WHITE
                    ground = cls.SEL if chosen else color
                    if line2:
                        c.text(cx + 5, ry + 5, line1, ink, ground, 2)
                        c.text(cx + 5, ry + 24, line2, ink, ground, 2)
                    else:
                        c.text(cx + 5, ry + 15, line1, ink, ground, 2)
        sy = gy + 30 + cls.rows * rh + 2
        c.rect(24, sy, 592, 22, cls.HEAD)
        c.text(36, sy + 7, 'L/R PAGE   LEFT/RIGHT TIME   A WATCH   Y INFO   START LOOK', cls.WHITE, cls.HEAD, 1)
        addr, code = app.studio_lines()
        if addr:
            c.text(24, 462, fit('Edit channels: %s  code %s' % (addr, code or '----'), 70), cls.WHITE, cls.BG, 1)


class Modern:
    cols, rows = 2, 5
    SHADE, ROW, ROW_SEL = rgb(0, 0, 0, 205), rgb(18, 22, 30, 200), rgb(36, 90, 120, 225)
    ACCENT, WHITE, DIM, BAR_BG = rgb(0, 200, 210), rgb(255, 255, 255), rgb(170, 180, 190), rgb(70, 78, 90, 220)

    @classmethod
    def draw(cls, app, c, now):
        n = len(app.channels)
        top_y = 150
        c.rect(0, top_y, 640, 480 - top_y, cls.SHADE)                  # the picture stays visible above
        c.text(40, top_y + 12, 'GUIDE', cls.ACCENT, cls.SHADE, 3)
        stamp = '%s  %s' % (now.strftime('%a %d %b'), clock12(now))
        c.text(600 - c.text_width(stamp), top_y + 18, stamp, cls.WHITE, cls.SHADE, 2)
        rows, rh = cls.rows, 44
        top = max(0, min(app.guide_sel - rows // 2, n - rows))
        at = app.guide_at
        for r in range(min(rows, n)):
            i = top + r
            ch = app.channels[i]
            y = top_y + 46 + r * (rh + 2)
            sel = i == app.guide_sel
            bg = cls.ROW_SEL if sel else cls.ROW
            c.rect(40, y, 560, rh, bg)
            c.rect(40, y, 5 if sel else 3, rh, cls.ACCENT if sel else cls.DIM)
            c.text(54, y + 6, '%d' % ch.number, cls.WHITE, bg, 2)
            put(c, 54, y + 33, 72, ch.name, cls.DIM, bg, 1, 2)
            cur = cell_at(app, ch, at)
            nxt = cell_at(app, ch, cur.end) if cur else None
            if cur:
                put(c, 130, y + 13, 266, cur.title, cls.WHITE, bg)
                if cur.start <= now < cur.end:
                    total = (cur.end - cur.start).total_seconds()
                    done = min(1.0, (now - cur.start).total_seconds() / total)
                    c.rect(130, y + 32, 150, 5, cls.BAR_BG)
                    c.rect(130, y + 32, int(150 * done), 5, cls.ACCENT)
                    c.text(290, y + 30, '%d min left' % max(0, int((cur.end - now).total_seconds() // 60)), cls.DIM, bg, 1)
                else:
                    c.text(130, y + 30, '%s - %s' % (clock12(cur.start), clock12(cur.end)), cls.DIM, bg, 1)
            if nxt:
                c.text(404, y + 8, 'NEXT ' + clock12(nxt.start), cls.ACCENT, bg, 1)
                c.text(404, y + 22, fit(nxt.title, 23), cls.WHITE, bg, 1)
        c.text(40, 458, 'UP/DOWN CHANNEL  LEFT/RIGHT TIME  A WATCH  Y INFO  START LOOK', cls.DIM, cls.SHADE, 1)


class Classic:
    cols, rows = 2, 8

    @classmethod
    def draw(cls, app, c, now):
        BLUE, DARK, MID, SEL = rgb(0, 0, 112), rgb(0, 0, 64), rgb(0, 0, 150), rgb(0, 112, 160)
        WHITE, YELLOW, CYAN = rgb(255, 255, 255), rgb(255, 224, 0), rgb(96, 224, 255)
        n = len(app.channels)
        c.rect(24, 24, 592, 432, DARK)
        c.rect(24, 24, 592, 40, MID)
        c.text(40, 32, 'TV GUIDE', YELLOW, MID, 3)
        t = '%d/%d %s' % (now.month, now.day, clock12(now))
        c.text(600 - c.text_width(t), 40, t, WHITE, MID, 2)
        win = app.guide_win
        c.rect(24, 64, 592, 24, MID)
        for k in range(2):
            c.text(208 + k * 200 + 4, 68, clock12(win + HALF_HOUR * k), CYAN, MID, 2)
        top = max(0, min(app.guide_sel - 3, n - cls.rows))
        for r in range(min(cls.rows, n)):
            i = top + r
            ch = app.channels[i]
            y = 92 + r * 40
            sel = i == app.guide_sel
            bg = SEL if sel else (BLUE if r % 2 == 0 else DARK)
            c.rect(24, y, 592, 38, bg)
            put(c, 32, y + 19, 168, '%d %s' % (ch.number, ch.name.upper()), YELLOW if sel else CYAN, bg, 2, 2)
            for k in range(2):
                cc = cell_at(app, ch, win + HALF_HOUR * k)
                c.rect(208 + k * 200 - 4, y, 4, 38, DARK)
                if cc:
                    put(c, 208 + k * 200 + 4, y + 19, 188, cc.title, WHITE, bg, 2, 2)
        addr, code = app.studio_lines()
        if addr:
            c.rect(24, 416, 592, 40, MID)
            c.text(40, 424, fit('EDIT CHANNELS: %s' % addr, 70), CYAN, MID, 1)
            c.text(40, 438, fit('CODE %s  Y: INFO  START: LOOK  X: GUIDE' % (code or '----'), 70), WHITE, MID, 1)


def draw_info(app, c, now):
    """The details of the highlighted programme over the lower part of any look: what it is, when, and the server's description."""
    ch, cell = selected_cell(app, now)
    PANEL, HEAD, WHITE, YELLOW, CYAN = rgb(6, 16, 70), rgb(24, 56, 160), rgb(255, 255, 255), rgb(255, 224, 80), rgb(120, 220, 255)
    x, y, w, h = 24, 104, 592, 352
    c.rect(x, y, w, h, PANEL)
    c.rect(x, y, w, 4, YELLOW)
    c.rect(x, y + h - 4, w, 4, YELLOW)
    if not cell or cell.item.kind == 'filler':
        c.text(x + 16, y + 20, 'Nothing is scheduled here.', WHITE, PANEL, 2)
        return
    it = cell.item
    film = it.kind == 'movie'
    head = it.title if film or not it.show else it.show
    top = y + 16
    for row in (wrap_words(head, (w - 32) // 16) or [fit(head, (w - 32) // 16)])[:2]:
        c.text(x + 16, top, row, YELLOW, PANEL, 2)
        top += 20
    if not film and it.show:
        ep = ('S%02dE%02d  ' % (it.season, it.episode)) if it.season or it.episode else ''
        for row in (wrap_words(ep + it.title, (w - 32) // 16) or [fit(ep + it.title, (w - 32) // 16)])[:2]:
            c.text(x + 16, top, row, WHITE, PANEL, 2)
            top += 20
    top += 4
    mins = max(1, int((cell.end - cell.start).total_seconds() // 60))
    bits = ['%s-%s' % (clock12(cell.start, True), clock12(cell.end, True)), '%d min' % mins]
    if it.year:
        bits.append(str(it.year))
    if it.rating:
        bits.append(str(it.rating))
    c.rect(x + 8, top, w - 16, 20, HEAD)
    put(c, x + 16, top + 10, w - 32, '   '.join(bits), WHITE, HEAD, 2, 1, True)
    top += 26
    c.text(x + 16, top, fit('CH %d  %s' % (ch.number, ch.name.upper()), 68), CYAN, PANEL, 1)
    top += 16
    text = (it.overview or '').strip() or 'No description from the server. Re-index the source in Studio to fetch descriptions.'
    room = (y + h - 30 - top) // 11
    rows = wrap_words(' '.join(text.split()), 68) or [fit(text, 68)]
    if len(rows) > room:
        rows = rows[:room]
        rows[-1] = fit(rows[-1] + ' ..', 68)
    for row in rows:
        c.text(x + 16, top, row, WHITE, PANEL, 1)
        top += 11
    c.text(x + 16, y + h - 20, 'Y or B: close   A: watch this channel', rgb(150, 205, 255), PANEL, 1)


LOOKS = {'satellite': Satellite, 'cable': Cable, 'modern': Modern, 'classic': Classic}


def look(name):
    return LOOKS.get(name) or LOOKS[DEFAULT_THEME]


def next_theme(name):
    names = [k for k, _ in THEMES]
    return names[(names.index(name) + 1) % len(names)] if name in names else DEFAULT_THEME
