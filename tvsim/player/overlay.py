"""On-screen graphics: a 640x480 ARGB canvas drawn with the 8x8 font, shown by the H.264 core
over the picture (or over black) from pages at the end of the Linux framebuffer (/dev/fb0).

Pixels are either opaque or fully transparent (all zero)."""
import os

from .font8x8 import FONT

OV_W, OV_H = 640, 480
PAGE_BYTES = OV_W * OV_H * 4
PAGES = 3


def rgb(r, g, b):
    return bytes((b, g, r, 255))


class Canvas:
    def __init__(self, w=OV_W, h=OV_H):
        self.w, self.h = w, h
        self.buf = bytearray(w * h * 4)
        self._glyphs = {}

    def clear(self):
        self.buf[:] = bytes(len(self.buf))

    def noise(self):
        """Grey TV static over the whole canvas (a fresh pattern each call; a few milliseconds)."""
        n = self.w * self.h
        g = os.urandom(n)
        self.buf[0::4] = g
        self.buf[1::4] = g
        self.buf[2::4] = g
        self.buf[3::4] = bytes([255]) * n

    def rect(self, x, y, w, h, color):
        x0, x1 = max(0, x), min(self.w, x + w)
        if x1 <= x0:
            return
        row = color * (x1 - x0)
        for j in range(max(0, y), min(self.h, y + h)):
            o = (j * self.w + x0) * 4
            self.buf[o:o + len(row)] = row

    def _glyph(self, ch, fg, bg, scale):
        key = (ch, fg, bg, scale)
        g = self._glyphs.get(key)
        if g is None:
            bits = FONT[ord(ch) if ord(ch) < 256 else 63]
            rows = []
            for r in range(8):
                row = b''.join((fg if bits[r] >> c & 1 else bg) * scale for c in range(8))
                rows += [row] * scale
            g = self._glyphs[key] = rows
        return g

    def text(self, x, y, s, fg, bg, scale=2):
        """Draw `s` with its cell background `bg` (text always sits on an opaque bar)."""
        cw = 8 * scale
        for i, ch in enumerate(s):
            px = x + i * cw
            if px < 0 or px + cw > self.w:
                continue
            for j, row in enumerate(self._glyph(ch, fg, bg, scale)):
                if 0 <= y + j < self.h:
                    o = ((y + j) * self.w + px) * 4
                    self.buf[o:o + cw * 4] = row

    def text_width(self, s, scale=2):
        return len(s) * 8 * scale


def console_bind(on, root='/sys/class/vtconsole'):
    """Attach/detach the Linux text console from the framebuffer so its cursor does not draw through our overlay."""
    changed = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return changed
    for name in names:
        try:
            with open(os.path.join(root, name, 'name'), encoding='utf-8', errors='replace') as f:
                if 'frame buffer' not in f.read().lower():
                    continue
            with open(os.path.join(root, name, 'bind'), 'w') as f:
                f.write('1' if on else '0')
            changed.append(name)
        except OSError:
            continue
    return changed


def console_graphics(on, tty_paths=('/dev/tty0', '/dev/tty1')):
    try:
        import fcntl
    except ImportError:
        return False
    for path in tty_paths:
        try:
            fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        except OSError:
            continue
        try:
            fcntl.ioctl(fd, 0x4B3A, 1 if on else 0)           # KDSETMODE: KD_GRAPHICS / KD_TEXT
            return True
        except OSError:
            continue
        finally:
            os.close(fd)
    return False


class Overlay:
    """Three 640x480 ARGB pages at the far end of the framebuffer; the core shows one, we draw on another."""

    def __init__(self, ring, log=print):
        import fcntl
        import mmap
        import struct
        self.ring, self.log = ring, log
        self.fd = os.open('/dev/fb0', os.O_RDWR)
        info = bytearray(160)
        fcntl.ioctl(self.fd, 0x4602, info)                    # FBIOGET_FSCREENINFO
        self.start, self.length = struct.unpack('<II', bytes(info[16:24]))
        if self.length < PAGES * PAGE_BYTES or self.start % 4096:
            raise RuntimeError('The framebuffer is too small for the overlay.')
        self.map = mmap.mmap(self.fd, self.length, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        self.detached = bool(console_bind(False))
        console_graphics(True)
        self.shown = None
        self.pending = None
        self.canvas = Canvas()

    def _page(self, i):
        return self.length - (PAGES - i) * PAGE_BYTES          # offset inside the framebuffer

    def _acked(self):
        if self.pending is None:
            return True
        gen, state, err = self.ring.overlay_seen()
        if state == 2:
            raise RuntimeError('The core refused the overlay (error %d).' % err)
        if (gen - self.pending) & 0xFFFFFFFF < 0x80000000:
            self.pending = None
            return True
        return False

    def show(self):
        """Show the canvas. -> False when the core has not yet taken the previous page (try again soon)."""
        if not self._acked():
            return False
        idx = next(i for i in range(PAGES) if i != self.shown)
        off = self._page(idx)
        self.map[off:off + PAGE_BYTES] = self.canvas.buf
        self.pending = self.ring.overlay_show(self.start + off, OV_W, OV_H, OV_W * 4, '8888')
        self.shown = idx
        return True

    def hide(self):
        self.pending = self.ring.overlay_hide()
        self.shown = None

    def close(self):
        try:
            self.ring.overlay_hide()
        except Exception:
            pass
        try:
            self.map.close()
            os.close(self.fd)
        except (OSError, ValueError, BufferError):
            pass
        if self.detached:
            console_bind(True)
        console_graphics(False)
