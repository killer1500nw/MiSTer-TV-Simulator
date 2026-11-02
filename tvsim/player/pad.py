"""Gamepad and keyboard as the H.264 core passes them on (its input region), turned into remote-control actions.

Actions: up down left right ok back menu guide pgup pgdn, and 'digit:N'.
"""

# controller bits as MiSTer's main program sends them: 0-3 = right, left, down, up, then A B X Y L R Select Start
JOY_BITS = {0: 'right', 1: 'left', 2: 'down', 3: 'up', 4: 'ok', 5: 'back', 6: 'guide', 7: 'menu',
            8: 'pgup', 9: 'pgdn', 10: 'guide', 11: 'menu'}
# PS/2 set-2 make codes as (extended, code)
PS2 = {(1, 0x75): 'up', (1, 0x72): 'down', (1, 0x6B): 'left', (1, 0x74): 'right',
       (0, 0x5A): 'ok', (1, 0x5A): 'ok', (0, 0x29): 'ok', (0, 0x76): 'back', (0, 0x66): 'back',
       (0, 0x34): 'guide', (0, 0x0D): 'guide', (0, 0x3A): 'menu', (0, 0x1A): 'menu', (1, 0x7D): 'pgup', (1, 0x7A): 'pgdn',
       (0, 0x49): 'up', (0, 0x41): 'down'}          # '.' and ',' as channel up / down
for _code, _digit in ((0x45, 0), (0x16, 1), (0x1E, 2), (0x26, 3), (0x25, 4), (0x2E, 5), (0x36, 6), (0x3D, 7),
                      (0x3E, 8), (0x46, 9), (0x70, 0), (0x69, 1), (0x72, 2), (0x7A, 3), (0x6B, 4), (0x73, 5),
                      (0x74, 6), (0x6C, 7), (0x75, 8), (0x7D, 9)):
    PS2[(0, _code)] = 'digit:%d' % _digit


class Pad:
    def __init__(self, ring):
        self.ring = ring
        pads, self.count = ring.input_snapshot()
        self.prev = self._joy(pads)

    @staticmethod
    def _joy(pads):
        joy = 0
        for p in pads:
            joy |= p
        return joy & 0xFFF

    def poll(self):
        """-> the actions since the last call."""
        out = []
        pads, _ = self.ring.input_snapshot()
        joy = self._joy(pads)
        if joy != self.prev:
            for bit, action in JOY_BITS.items():
                if (joy >> bit & 1) and not (self.prev >> bit & 1):
                    out.append(action)
            self.prev = joy
        self.count, events = self.ring.input_events(self.count)
        for ev in events:
            if (ev >> 14) != 0:
                continue                                         # not a key
            ext, code, down = ev >> 8 & 1, ev & 0xFF, ev >> 9 & 1
            if down and (ext, code) in PS2:
                out.append(PS2[(ext, code)])
        return out
