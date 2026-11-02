"""Picture shapes for a 4:3 screen, chosen with one button and remembered per show.

Every mode is a list of crop steps applied to the stream's sequence header (see h264sps.crop_shape): a few bytes per keyframe,
no re-encoding. The core itself stays on Letterbox, so a picture that is not 4:3 gets bars unless a mode trims it.
"""
import json

MODES = [
    ('Fit', 'Whole picture, bars if needed', []),
    ('Fill', 'Sides trimmed to fill 4:3', [(4, 3)]),
    ('14:9', 'Sides trimmed to 14:9', [(14, 9)]),
    ('Zoom 16:9', 'Cut 16:9 bars baked in, fill', [(16, 9), (4, 3)]),
    ('Zoom 2.35', 'Cut wide-film bars, then fill', [(47, 20), (4, 3)]),
]
NAMES = [m[0] for m in MODES]


class AspectBook:
    def __init__(self, path, default='Fit'):
        self.path = path
        self.default = default if default in NAMES else 'Fit'
        try:
            with open(path, encoding='utf-8') as f:
                self.saved = {k: v for k, v in json.load(f).items() if v in NAMES}
        except (OSError, ValueError):
            self.saved = {}

    @staticmethod
    def key(item):
        """A whole series shares a setting (it is usually the whole upload that is wrong); a film has its own."""
        return 'show:' + item.show if item.show and item.kind == 'episode' else 'item:' + item.id

    def mode(self, item):
        return self.saved.get(self.key(item), self.default)

    def steps(self, item):
        return list(MODES[NAMES.index(self.mode(item))][2])

    def describe(self, item):
        name = self.mode(item)
        return name, MODES[NAMES.index(name)][1]

    def cycle(self, item, step=1):
        name = NAMES[(NAMES.index(self.mode(item)) + step) % len(NAMES)]
        self.saved[self.key(item)] = name
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.saved, f, indent=1)
        except OSError:
            pass
        return name
