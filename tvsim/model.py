"""Data model: catalog items, pools, channels. Plain dataclasses, JSON-friendly."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Item:
    id: str                      # stable id, e.g. "jf:abc123" or "plex:5521"
    title: str
    duration: int                # seconds
    kind: str = "episode"        # episode | movie | commercial | bumper
    show: str = ""               # series name (episodes)
    season: int = 0
    episode: int = 0
    direct_ok: bool = True       # False -> needs server/PC transcode
    media: str = ''              # where the file is on the server (Plex: the part's key); Jellyfin needs none


@dataclass
class Pool:
    name: str
    item_ids: List[str]
    mode: str = "shuffle"        # shuffle | sequential


@dataclass
class Daypart:
    start: int                   # minutes after midnight
    end: int                     # minutes after midnight (exclusive)
    pools: List[str]             # pool names eligible in this block


@dataclass
class Channel:
    number: int
    name: str
    pools: List[Pool]
    dayparts: List[Daypart]
    commercial_pool: Optional[str] = None
    slot_minutes: int = 30       # programmes snap to this grid
    no_repeat_hours: int = 12    # avoid replaying an item inside this window
    max_break_minutes: int = 15  # an ad break never runs longer than this (and only fills time the grid leaves free)
    anchor: str = "2024-01-01"   # sequential pools count from this date
    meta: dict = field(default_factory=dict)
