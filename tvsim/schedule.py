"""Deterministic live-TV scheduler.

Every day of a channel is generated from a seed of (channel number, date), so
the MiSTer and the PC editor always agree on what is on without sharing a
schedule file, and tuning in mid-programme just means seeking to the right
offset. Cheap enough for the MiSTer's ARM (a day is ~50 list operations).
"""
import datetime as dt
import random
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .model import Channel, Item


@dataclass
class Airing:
    start: int          # seconds since local midnight of the day
    end: int
    item: Item          # kind 'filler' = slate with no media (ident / colour bars)
    slot: int           # grid slot index; groups a programme with its ad break


FILLER = Item(id="filler", title="Station ident", duration=0, kind="filler")
DAY = 86400


class Scheduler:
    def __init__(self, items: Dict[str, Item]):
        self.items = items
        self._seq_start: Dict[Tuple[int, str, str], int] = {}
        self._seq_used: Dict[Tuple[int, str, str], int] = {}
        self._days: Dict[Tuple[int, str], List[Airing]] = {}
        self._ad_ids: Dict[int, set] = {}

    def _daypart_pools(self, ch: Channel, minute: int) -> List[str]:
        for dp in ch.dayparts:
            if dp.start <= minute < dp.end:
                return dp.pools
        return []

    def _seq_pos(self, ch: Channel, pool: str, day: dt.date) -> int:
        """How far through a sequential pool we are at the start of `day`."""
        key = (ch.number, pool, day.isoformat())
        if key in self._seq_start:
            return self._seq_start[key]
        # Replay forward from the anchor date (iteratively, cached per day).
        # Reset `anchor` in the channel to bound the cost on a slow CPU.
        d, pos = dt.date.fromisoformat(ch.anchor), 0
        while d < day:
            self._seq_start[(ch.number, pool, d.isoformat())] = pos
            used_key = (ch.number, pool, d.isoformat())
            if used_key not in self._seq_used:
                self.day(ch, d)
            pos += self._seq_used[used_key]
            d += dt.timedelta(days=1)
        self._seq_start[key] = pos
        return pos

    def day(self, ch: Channel, day: dt.date) -> List[Airing]:
        key = (ch.number, day.isoformat())
        out = self._days.get(key)
        if out is None:
            out = self._days[key] = self._build_day(ch, day)
        return out

    def _build_day(self, ch: Channel, day: dt.date) -> List[Airing]:
        rng = random.Random(f"{ch.number}:{day.isoformat()}")
        pools = {p.name: p for p in ch.pools}
        seq_taken = {p.name: 0 for p in ch.pools}
        recent: Dict[str, int] = {}
        ads = ([self.items[i] for i in pools[ch.commercial_pool].item_ids
                if i in self.items] if ch.commercial_pool in pools else [])
        out: List[Airing] = []
        slot_s = ch.slot_minutes * 60
        window = ch.no_repeat_hours * 3600
        t, slot = 0, 0
        while t < DAY:
            names = self._daypart_pools(ch, t // 60)
            item = None
            if names:
                p = pools[rng.choice(names)]
                ids = [i for i in p.item_ids if i in self.items]
                if ids and p.mode == "sequential":
                    pos = self._seq_pos(ch, p.name, day) + seq_taken[p.name]
                    item = self.items[ids[pos % len(ids)]]
                    seq_taken[p.name] += 1
                elif ids:
                    fresh = [i for i in ids if t - recent.get(i, -10**9) > window]
                    item = self.items[rng.choice(fresh or ids)]
                    recent[item.id] = t
            if item is None:
                out.append(Airing(t, min(t + slot_s, DAY), FILLER, slot))
                t += slot_s
                slot += 1
                continue
            dur = max(item.duration, 1)
            slots = -(-dur // slot_s)                     # ceil to the grid
            block_end = min(t + slots * slot_s, DAY)
            end = min(t + dur, block_end)
            out.append(Airing(t, end, item, slot))
            t = end
            # The ad break fills what the grid leaves free after the programme (none if the programme fills it),
            # but never more than max_break_minutes: if more is free, the next programme simply starts earlier.
            break_end = min(block_end, t + ch.max_break_minutes * 60)
            while t < break_end:
                fits = [a for a in ads if 0 < a.duration <= break_end - t]
                if not fits:
                    out.append(Airing(t, break_end, FILLER, slot))
                    t = break_end
                    break
                ad = rng.choice(fits)
                out.append(Airing(t, t + ad.duration, ad, slot))
                t += ad.duration
            slot += slots
        for name, n in seq_taken.items():
            self._seq_used[(ch.number, name, day.isoformat())] = n
        return out

    def is_ad(self, ch: Channel, item: Item) -> bool:
        """Is `item` one of the channel's commercials? (ads are ordinary library items; only the pool says so)"""
        key = ch.number
        if key not in self._ad_ids:
            pool = next((p for p in ch.pools if p.name == ch.commercial_pool), None)
            self._ad_ids[key] = set(pool.item_ids) if pool else set()
        return item.id in self._ad_ids[key]

    def programme(self, ch: Channel, when: dt.datetime) -> Airing:
        """The main programme of the slot containing `when` (not the ad in progress), for guides and banners."""
        airing, _ = self.now(ch, when)
        for a in self.day(ch, when.date()):
            if a.slot == airing.slot:
                return a
        return airing

    def now(self, ch: Channel, when: dt.datetime) -> Tuple[Airing, int]:
        """What is on at `when`, and how many seconds into it to seek."""
        sec = when.hour * 3600 + when.minute * 60 + when.second
        for a in self.day(ch, when.date()):
            if a.start <= sec < a.end:
                return a, sec - a.start
        raise RuntimeError("schedule has a gap")  # day() always tiles 0..DAY
