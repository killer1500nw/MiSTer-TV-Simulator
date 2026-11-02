"""Render the player's on-screen graphics to PNG files on the PC (no MiSTer needed).

    python tools/preview_overlay.py build outdir
"""
import datetime as dt
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tvsim.player.app import App  # noqa: E402
from tvsim.player.overlay import Canvas  # noqa: E402


def png(path, canvas, backdrop=(40, 40, 40)):
    w, h, b = canvas.w, canvas.h, canvas.buf
    rows = []
    for j in range(h):
        row = bytearray([0])
        for i in range(w):
            o = (j * w + i) * 4
            if b[o + 3]:
                row += bytes((b[o + 2], b[o + 1], b[o]))
            else:
                row += bytes(backdrop)
        rows.append(bytes(row))

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))


def main():
    folder, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(folder, 'config.json'), 'w') as f:
        f.write('{"server": "http://x", "api_key": "x"}')
    try:
        app = App(folder, print)
        assert app.load_data()
    finally:
        os.remove(os.path.join(folder, 'config.json'))
    now = dt.datetime.now().replace(hour=20, minute=12)
    c = Canvas()
    app.idx = 1
    app.draw_banner(c, now)
    png(os.path.join(out, 'banner.png'), c)
    c.clear()
    app.guide_sel = 2
    app.draw_guide(c, now)
    app.draw_guide_footer(c)
    png(os.path.join(out, 'guide.png'), c)
    c.clear()
    app.digits = '4'
    app.draw_digits(c)
    png(os.path.join(out, 'digits.png'), c)
    c.clear()
    app.aspect_msg = 'ZOOM 16:9: Cut the baked-in bars of a 16:9 picture, then fill'
    app.draw_aspect(c)
    png(os.path.join(out, 'aspect.png'), c)
    c.clear()
    app.slate = ('SCI-FI CHANNEL', 'Back in a moment')
    app.draw_slate(c)
    png(os.path.join(out, 'slate.png'), c)
    c.clear()
    app.tuning = 'CH 05'
    app.draw_tuning(c)
    png(os.path.join(out, 'tuning.png'), c)
    c.clear()
    app.draw_setup(c)
    png(os.path.join(out, 'setup.png'), c)
    print('wrote PNGs to', out)


if __name__ == '__main__':
    main()
