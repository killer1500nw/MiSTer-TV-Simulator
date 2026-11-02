import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.model import Channel, Daypart, Item, Pool
from tvsim.schedule import Scheduler, DAY


def make():
    items = {}
    for i in range(10):
        items[f"e{i}"] = Item(f"e{i}", f"Ep {i}", 22 * 60, show="Cartoon", episode=i)
    items["m1"] = Item("m1", "Movie", 95 * 60, kind="movie")
    for i, d in enumerate((15, 30, 45, 60)):
        items[f"a{i}"] = Item(f"a{i}", f"Ad {i}", d, kind="commercial")
    ch = Channel(
        7, "Toon TV",
        pools=[Pool("toons", [f"e{i}" for i in range(10)], "sequential"),
               Pool("movies", ["m1"]), Pool("ads", [f"a{i}" for i in range(4)])],
        dayparts=[Daypart(0, 720, ["toons"]), Daypart(720, 1440, ["movies", "toons"])],
        commercial_pool="ads", anchor="2026-10-01")
    return Scheduler(items), ch


class T(unittest.TestCase):
    def test_tiles_whole_day(self):
        s, ch = make()
        day = s.day(ch, dt.date(2026, 11, 2))
        self.assertEqual(day[0].start, 0)
        self.assertEqual(day[-1].end, DAY)
        for a, b in zip(day, day[1:]):
            self.assertEqual(a.end, b.start)

    def test_deterministic(self):
        s, ch = make()
        s2, _ = make()
        d = dt.date(2026, 11, 2)
        self.assertEqual([(a.start, a.item.id) for a in s.day(ch, d)],
                         [(a.start, a.item.id) for a in s2.day(ch, d)])

    def test_sequential_continues_next_day(self):
        s, ch = make()
        d1 = dt.date(2026, 11, 2)
        eps = [a.item.episode for a in s.day(ch, d1) if a.item.kind == "episode"]
        nxt = [a.item.episode for a in s.day(ch, d1 + dt.timedelta(days=1))
               if a.item.kind == "episode"][0]
        self.assertEqual(nxt, (eps[-1] + 1) % 10)

    def test_ad_breaks_are_capped_and_only_fill_free_time(self):
        s, ch = make()
        for d in range(5):
            day = s.day(ch, dt.date(2026, 11, 2 + d))
            for slot in {a.slot for a in day}:
                block = [a for a in day if a.slot == slot]
                prog, rest = block[0], block[1:]
                if prog.item.kind == "filler":
                    continue
                self.assertLessEqual(sum(a.end - a.start for a in rest), 15 * 60)
                grid = -(-(prog.item.duration) // 1800) * 1800
                self.assertLessEqual(prog.item.duration + sum(a.end - a.start for a in rest), max(grid, prog.item.duration))

    def test_twenty_minute_show_gets_at_most_ten_minutes_of_ads(self):
        s, ch = make()
        ch.dayparts = [Daypart(0, 1440, ["toons"])]
        ch.pools[0].item_ids = ["e0"]
        ch.pools[0].item_ids.sort()
        s.items["e0"] = Item("e0", "Twenty", 20 * 60, show="Cartoon")
        day = s.day(ch, dt.date(2026, 11, 2))
        self.assertEqual(day[0].item.id, "e0")
        self.assertLessEqual(sum(a.end - a.start for a in day if a.slot == day[0].slot and a is not day[0]), 10 * 60)
        self.assertEqual(day[0].end - day[0].start, 20 * 60)

    def test_no_ads_when_the_programme_fills_the_slot(self):
        s, ch = make()
        ch.dayparts = [Daypart(0, 1440, ["toons"])]
        s.items["e0"] = Item("e0", "Half hour", 30 * 60, show="Cartoon")
        ch.pools[0].item_ids = ["e0"]
        day = s.day(ch, dt.date(2026, 11, 2))
        self.assertEqual([a.item.id for a in day[:3]], ["e0", "e0", "e0"])

    def test_now_offset(self):
        s, ch = make()
        a, off = s.now(ch, dt.datetime(2026, 11, 2, 0, 10, 0))
        self.assertEqual(a.start + off, 600)


if __name__ == "__main__":
    unittest.main()
