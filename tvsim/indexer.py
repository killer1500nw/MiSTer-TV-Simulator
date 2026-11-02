"""Index a Jellyfin server into catalog.json for the MiSTer 90s TV Simulator.

    set JELLYFIN_API_KEY=...
    python -m tvsim.indexer --server http://localhost:8096 --out catalog.json

The catalog holds every playable item (with a direct/transcode verdict) and the
groups a channel can draw from: libraries, series, playlists and collections.
The API key is never written to the file.
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys

from .jellyfin import Jellyfin
from .verdict import verdict

TYPES = 'Movie,Episode'
FIELDS = 'MediaStreams,ProductionYear,OfficialRating,SeriesId,SeriesName'


def item_record(row, slug='jf'):
    video = next((s for s in row.get('MediaStreams', []) if s.get('Type') == 'Video'), None)
    ok, why = verdict(video)
    ticks = row.get('RunTimeTicks') or 0
    rec = {
        'id': '%s:%s' % (slug, row['Id']),
        'title': row.get('Name', ''),
        'duration': int(ticks // 10_000_000),
        'kind': 'movie' if row.get('Type') == 'Movie' else 'episode',
        'show': row.get('SeriesName', ''),
        'season': row.get('ParentIndexNumber') or 0,
        'episode': row.get('IndexNumber') or 0,
        'year': row.get('ProductionYear'),
        'rating': row.get('OfficialRating'),
        'direct_ok': ok,
        'why': why,
    }
    if video:
        rec['video'] = {k: video.get(k) for k in ('Codec', 'Profile', 'Width', 'Height', 'RealFrameRate', 'BitRate')}
    return rec


def build(jf, log=print, slug='jf'):
    items, series = {}, collections.OrderedDict()
    skipped = 0
    for row in jf.items(Recursive='true', IncludeItemTypes=TYPES, Fields=FIELDS):
        rec = item_record(row, slug)
        if rec['duration'] <= 0:
            skipped += 1                       # no runtime: the file is missing or unreadable
            continue
        items[rec['id']] = rec
        if row.get('SeriesId'):
            series.setdefault(row['SeriesId'], {'name': row.get('SeriesName', ''), 'ids': []})['ids'].append(rec['id'])
    log('%d items (%d skipped without a runtime)' % (len(items), skipped))

    groups = []

    def add(kind, gid, name, ids):
        ids = [i for i in ids if i in items]
        if ids:
            groups.append({'id': gid, 'type': kind, 'name': name, 'item_ids': ids, 'source': slug})

    for lib in jf.libraries():
        rows = jf.items(ParentId=lib['ItemId'], Recursive='true', IncludeItemTypes=TYPES)
        add('library', slug + ':' + lib['ItemId'], lib['Name'], [slug + ':' + r['Id'] for r in rows])
    for sid, s in series.items():
        s['ids'].sort(key=lambda i: (items[i]['season'], items[i]['episode']))
        add('series', slug + ':' + sid, s['name'], s['ids'])
    for p in jf.items(Recursive='true', IncludeItemTypes='Playlist'):
        add('playlist', slug + ':' + p['Id'], p['Name'], [slug + ':' + r['Id'] for r in jf.playlist_items(p['Id'])])
    for b in jf.items(Recursive='true', IncludeItemTypes='BoxSet'):
        rows = jf.items(ParentId=b['Id'], Recursive='true', IncludeItemTypes=TYPES)
        add('collection', slug + ':' + b['Id'], b['Name'], [slug + ':' + r['Id'] for r in rows])
    return {
        'source': {'type': 'jellyfin', 'base': jf.base, 'id': slug},
        'generated': dt.datetime.now().isoformat(timespec='seconds'),
        'items': items,
        'groups': groups,
    }


def summary(cat):
    items = cat['items'].values()
    direct = sum(1 for i in items if i['direct_ok'])
    reasons = collections.Counter(
        i['why'] if i['why'].split(' ')[0] in ('codec', 'profile') else i['why'].split(' ')[0]
        for i in cat['items'].values() if not i['direct_ok'])
    hours = sum(i['duration'] for i in cat['items'].values()) / 3600.0
    lines = ['%d items, %.0f hours; %d direct on the FPGA, %d need a transcode' % (
        len(cat['items']), hours, direct, len(cat['items']) - direct)]
    lines += ['  transcode because: %-22s %d' % (k.strip(), n) for k, n in reasons.most_common()]
    kinds = collections.Counter(g['type'] for g in cat['groups'])
    plural = {'library': 'libraries', 'series': 'series', 'playlist': 'playlists', 'collection': 'collections'}
    lines.append('groups: ' + ', '.join('%d %s' % (n, plural[k] if n != 1 else k) for k, n in kinds.items()))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--server', required=True)
    ap.add_argument('--out', default='catalog.json')
    a = ap.parse_args(argv)
    key = os.environ.get('JELLYFIN_API_KEY', '').strip()
    if not key:
        sys.exit('Set JELLYFIN_API_KEY first (Jellyfin dashboard > API keys).')
    cat = build(Jellyfin(a.server, key))
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(cat, f, ensure_ascii=False, indent=1)
    print(summary(cat))
    print('wrote', a.out)


if __name__ == '__main__':
    main()
