"""Turn the Studio's editable channel spec into what the player runs (channels + a slim item list).

Spec (what Studio saves, studio/spec.json):
  {"channels": [{"number": 2, "name": "Simpsons TV", "slot_minutes": 30, "no_repeat_hours": 12, "anchor": "2026-11-02",
     "pools": [{"name": "shows", "mode": "shuffle", "groups": ["jf:..."], "items": ["jf:..."],
                "filters": {"min_min": 5, "max_min": 130, "allow_transcode": true, "contains": ""}}],
     "commercials": {"groups": [...], "items": [], "filters": {...}},
     "dayparts": [{"start": 0, "end": 1440, "pools": ["shows"]}]}]}
"""
import datetime as dt

from ..model import Channel, Daypart, Pool
from ..store import ITEM_FIELDS

ADS = '_ads'


def pool_items(catalog, groups, spec, hidden=frozenset()):
    """Item ids for one pool spec: its groups and single items, then the filters. Order kept, duplicates dropped."""
    f = spec.get('filters') or {}
    lo, hi = f.get('min_min'), f.get('max_min')
    words = [w.strip().lower() for w in (f.get('contains') or '').split(',') if w.strip()]
    seen, out = set(), []
    ids = [i for g in spec.get('groups', []) for i in groups.get(g, {}).get('item_ids', [])] + list(spec.get('items', []))
    for i in ids:
        if i in seen or i not in catalog['items'] or i in hidden:
            continue
        seen.add(i)
        it = catalog['items'][i]
        if lo is not None and it['duration'] < lo * 60:
            continue
        if hi is not None and it['duration'] > hi * 60:
            continue
        if not f.get('allow_transcode', True) and not it['direct_ok']:
            continue
        if words and not any(w in (it['show'] + ' ' + it['title']).lower() for w in words):
            continue
        out.append(i)
    return out


def compile_channel(spec, catalog, groups, hidden=frozenset()):
    """-> (Channel, {pool name: ids})"""
    today = dt.date.today().isoformat()
    pools, resolved = [], {}
    for p in spec.get('pools', []):
        ids = pool_items(catalog, groups, p, hidden)
        resolved[p['name']] = ids
        pools.append(Pool(p['name'], ids, p.get('mode', 'shuffle')))
    ad_ids = pool_items(catalog, groups, spec['commercials'], hidden) if spec.get('commercials') else []
    if ad_ids:
        resolved[ADS] = ad_ids
        pools.append(Pool(ADS, ad_ids, 'shuffle'))
    names = [p.name for p in pools if p.name != ADS]
    dayparts = [Daypart(d['start'], d['end'], [n for n in d['pools'] if n in names]) for d in spec.get('dayparts', [])]
    if not dayparts:
        dayparts = [Daypart(0, 1440, names[:1])]
    ch = Channel(int(spec['number']), spec.get('name') or 'Channel %s' % spec['number'], pools, dayparts,
                 commercial_pool=ADS if ad_ids else None, slot_minutes=int(spec.get('slot_minutes', 30)),
                 no_repeat_hours=int(spec.get('no_repeat_hours', 12)),
                 max_break_minutes=int(spec.get('max_break_minutes', 15)), anchor=spec.get('anchor') or today)
    return ch, resolved


def pool_stats(catalog, ids):
    items = [catalog['items'][i] for i in ids]
    return {'items': len(items), 'hours': round(sum(i['duration'] for i in items) / 3600.0, 1),
            'direct': sum(1 for i in items if i['direct_ok'])}


def compile_all(spec, catalog, groups, hidden=frozenset()):
    """-> (channels, runtime items [dict], stats {channel number: {pool: stats}})"""
    channels, used, stats = [], set(), {}
    for cs in spec.get('channels', []):
        ch, resolved = compile_channel(cs, catalog, groups, hidden)
        stats[ch.number] = {n: pool_stats(catalog, ids) for n, ids in resolved.items()}
        if not any(ids for name, ids in resolved.items() if name != ADS):
            continue                                       # nothing to show: leave it out rather than play station idents all day
        channels.append(ch)
        for ids in resolved.values():
            used.update(ids)
    channels.sort(key=lambda c: c.number)
    items = [{k: catalog['items'][i][k] for k in ITEM_FIELDS if k in catalog['items'][i]} for i in sorted(used)]
    return channels, items, stats
