"""Load and save the files the player needs: catalog (items), channels and config."""
import dataclasses
import json

from .model import Channel, Daypart, Item, Pool

ITEM_FIELDS = ('id', 'title', 'duration', 'kind', 'show', 'season', 'episode', 'direct_ok', 'media', 'year', 'rating', 'overview')


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def items_from_catalog(cat):
    out = {}
    for rec in cat['items'].values() if isinstance(cat['items'], dict) else cat['items']:
        fields = {k: rec[k] for k in ITEM_FIELDS if k in rec}
        fields['year'] = int(fields.get('year') or 0)
        fields['rating'] = fields.get('rating') or ''
        fields['overview'] = fields.get('overview') or ''
        out[rec['id']] = Item(**fields)
    return out


def channels_from_json(data):
    chans = []
    for c in data['channels']:
        chans.append(Channel(
            number=c['number'], name=c['name'],
            pools=[Pool(**p) for p in c['pools']],
            dayparts=[Daypart(**d) for d in c['dayparts']],
            commercial_pool=c.get('commercial_pool'),
            slot_minutes=c.get('slot_minutes', 30),
            no_repeat_hours=c.get('no_repeat_hours', 12),
            max_break_minutes=c.get('max_break_minutes', 15),
            anchor=c.get('anchor', '2024-01-01'),
            meta=c.get('meta', {})))
    return sorted(chans, key=lambda c: c.number)


def channels_to_json(chans):
    return {'channels': [dataclasses.asdict(c) for c in chans]}
