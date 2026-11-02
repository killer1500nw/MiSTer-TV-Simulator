"""Index a Plex server into a catalog (same shape as the Jellyfin one: items + groups).

Libraries become groups of every movie / episode; shows, playlists and collections become groups too.
"""
import collections
import datetime as dt
import re

from .verdict import verdict


def parse_rate(text):
    """Plex's videoFrameRate ('24p', '60p', 'NTSC', 'PAL', '1080i', '29.97') -> (frames per second, probably interlaced)."""
    t = str(text or '').strip().lower()
    if t == 'ntsc':
        return 29.97, True                     # DVD-style video: assume interlaced and let the server clean it up
    if t == 'pal':
        return 25.0, True
    m = re.match(r'^(\d+(?:\.\d+)?)\s*([pi]?)$', t)
    if not m:
        return 0.0, False
    return float(m.group(1)), m.group(2) == 'i'


def video_facts(media):
    fps, interlaced = parse_rate(media.get('videoFrameRate'))
    return {'Codec': media.get('videoCodec'), 'Profile': media.get('videoProfile'), 'BitDepth': 8, 'PixelFormat': 'yuv420p',
            'IsInterlaced': interlaced, 'Width': media.get('width'), 'Height': media.get('height'), 'RealFrameRate': fps,
            'BitRate': (media.get('bitrate') or 0) * 1000}


def item_record(meta, slug):
    medias = meta.get('Media') or []
    if not medias:
        return None
    media = medias[0]
    parts = media.get('Part') or []
    ok, why = verdict(video_facts(media))
    key = parts[0].get('key', '') if len(parts) == 1 else ''
    if ok and not key:
        ok, why = False, 'file in several parts'
    # 'NTSC' / 'PAL' only guess at interlacing: such an item is checked against its own page when a channel actually uses it
    unchecked = why == 'interlaced' and str(media.get('videoFrameRate', '')).strip().lower() in ('ntsc', 'pal')
    return {
        'id': '%s:%s' % (slug, meta['ratingKey']),
        'title': meta.get('title', ''),
        'duration': int((meta.get('duration') or media.get('duration') or 0) // 1000),
        'kind': 'movie' if meta.get('type') == 'movie' else 'episode',
        'show': meta.get('grandparentTitle', ''),
        'season': meta.get('parentIndex') or 0,
        'episode': meta.get('index') or 0,
        'year': meta.get('year'),
        'rating': meta.get('contentRating'),
        'direct_ok': ok, 'why': why, 'media': key, 'unchecked': unchecked,
        'video': {'Codec': media.get('videoCodec'), 'Profile': media.get('videoProfile'), 'Width': media.get('width'),
                  'Height': media.get('height'), 'RealFrameRate': parse_rate(media.get('videoFrameRate'))[0],
                  'BitRate': (media.get('bitrate') or 0) * 1000},
    }


def refine(plex, rec):
    """The library listing only says 'NTSC'/'PAL' for a lot of video. The item's own page has the real stream facts
    (scan type, bit depth, frame rate), so re-judge it from those. Leaves rec alone if the server cannot say."""
    raw = rec['id'].split(':', 1)[1]
    try:
        meta = (plex.get('/library/metadata/%s' % raw).get('Metadata') or [None])[0]
        stream = next(s for s in meta['Media'][0]['Part'][0]['Stream'] if s.get('streamType') == 1)
    except (KeyError, IndexError, StopIteration, TypeError, OSError):
        return rec
    facts = {'Codec': stream.get('codec'), 'Profile': stream.get('profile'), 'BitDepth': stream.get('bitDepth') or 8,
             'PixelFormat': 'yuv420p' if stream.get('chromaSubsampling', '4:2:0') == '4:2:0' else 'other',
             'IsInterlaced': stream.get('scanType') == 'interlaced', 'Width': stream.get('width'), 'Height': stream.get('height'),
             'RealFrameRate': float(stream.get('frameRate') or 0), 'BitRate': (stream.get('bitrate') or 0) * 1000}
    ok, why = verdict(facts)
    if ok and not rec['media']:
        ok, why = False, 'file in several parts'
    rec['direct_ok'], rec['why'], rec['unchecked'] = ok, why, False
    rec['video'].update(RealFrameRate=facts['RealFrameRate'], Width=facts['Width'], Height=facts['Height'])
    return rec


def build(plex, log=print, slug='plex'):
    items, series, groups = {}, collections.OrderedDict(), []
    sections = [s for s in plex.sections() if s.get('type') in ('movie', 'show')]
    lib_ids = {}
    skipped = 0
    for sec in sections:
        ids = []
        for meta in plex.rows('/library/sections/%s/all' % sec['key'], type=1 if sec['type'] == 'movie' else 4):
            rec = item_record(meta, slug)
            if rec is None or rec['duration'] <= 0:
                skipped += 1
                continue
            items[rec['id']] = rec
            ids.append(rec['id'])
            if meta.get('grandparentRatingKey'):
                series.setdefault(meta['grandparentRatingKey'], {'name': meta.get('grandparentTitle', ''), 'ids': []})['ids'].append(rec['id'])
        lib_ids[sec['key']] = ids
    log('%d items (%d skipped without media or runtime)' % (len(items), skipped))
    def add(kind, gid, name, ids):
        ids = [i for i in ids if i in items]
        if ids:
            groups.append({'id': gid, 'type': kind, 'name': name, 'item_ids': ids, 'source': slug})

    for sec in sections:
        add('library', '%s:lib%s' % (slug, sec['key']), sec['title'], lib_ids[sec['key']])
    for key, s in series.items():
        s['ids'].sort(key=lambda i: (items[i]['season'], items[i]['episode']))
        add('series', '%s:%s' % (slug, key), s['name'], s['ids'])
    for p in plex.rows('/playlists', playlistType='video'):
        add('playlist', '%s:%s' % (slug, p['ratingKey']), p.get('title', ''),
            ['%s:%s' % (slug, m['ratingKey']) for m in plex.rows('/playlists/%s/items' % p['ratingKey'])])
    for sec in sections:
        for c in plex.rows('/library/sections/%s/collections' % sec['key']):
            ids = []
            for child in plex.rows('/library/collections/%s/children' % c['ratingKey']):
                if child.get('type') == 'show':                  # a collection of shows: all their episodes
                    ids += series.get(child['ratingKey'], {}).get('ids', [])
                else:
                    ids.append('%s:%s' % (slug, child['ratingKey']))
            add('collection', '%s:%s' % (slug, c['ratingKey']), c.get('title', ''), ids)
    return {'source': {'type': 'plex', 'base': plex.base, 'id': slug}, 'generated': dt.datetime.now().isoformat(timespec='seconds'),
            'items': items, 'groups': groups}
