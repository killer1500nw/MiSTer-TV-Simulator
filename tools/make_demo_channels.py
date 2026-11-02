"""Make demo channels.json + runtime_catalog.json from catalog.json (a stand-in for the Studio GUI).

    python tools/make_demo_channels.py [catalog.json] [outdir]
"""
import json
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tvsim.model import Channel, Daypart, Pool  # noqa: E402
from tvsim.store import ITEM_FIELDS, channels_to_json  # noqa: E402

# (number, name, words that must appear in show+title (any), slot minutes)
DEMO = [
    (2, 'Simpsons TV', ['simpsons'], 30),
    (3, 'Saturday Toons', ['captain planet', 'futurama'], 30),
    (4, 'Animation Zone', ['american dad', 'king of the hill'], 30),
    (5, 'Sci-Fi Channel', ['seaquest', 'sliders'], 60),
    (6, 'Music Zone', ['beavis'], 30),
    (7, 'Comedy Central', ['full frontal'], 60),
]


def main():
    cat_path = sys.argv[1] if len(sys.argv) > 1 else 'catalog.json'
    out = sys.argv[2] if len(sys.argv) > 2 else 'build'
    cat = json.load(open(cat_path, encoding='utf-8'))
    items = cat['items']
    ads = [i['id'] for i in items.values() if i['show'].lower() == 'fox8 ads' and i['direct_ok']]
    today = dt.date.today().isoformat()
    chans, used = [], set(ads)
    for number, name, words, slot in DEMO:
        ids = [i['id'] for i in items.values()
               if i['kind'] == 'episode' and 5 * 60 <= i['duration'] <= 130 * 60
               and any(w in (i['show'] + ' ' + i['title']).lower() for w in words)]
        if not ids:
            print('no items for', name)
            continue
        used.update(ids)
        pools = [Pool('shows', ids, 'shuffle')]
        if ads:
            pools.append(Pool('ads', ads, 'shuffle'))
        chans.append(Channel(number, name, pools, [Daypart(0, 1440, ['shows'])],
                             commercial_pool='ads' if ads else None, slot_minutes=slot, anchor=today))
        print('%d %-16s %4d items (%d direct)' % (number, name, len(ids), sum(items[i]['direct_ok'] for i in ids)))
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'channels.json'), 'w', encoding='utf-8') as f:
        json.dump(channels_to_json(chans), f, ensure_ascii=False)
    slim = [{k: items[i][k] for k in ITEM_FIELDS} for i in sorted(used)]
    with open(os.path.join(out, 'runtime_catalog.json'), 'w', encoding='utf-8') as f:
        json.dump({'items': slim}, f, ensure_ascii=False)
    print('%d channels, %d items -> %s' % (len(chans), len(slim), out))


if __name__ == '__main__':
    main()
