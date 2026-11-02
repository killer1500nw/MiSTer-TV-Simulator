import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.studio.compile import compile_all, pool_items


def item(i, mins, direct=True, show='S', title=None):
    return {'id': i, 'title': title or i, 'duration': mins * 60, 'kind': 'episode', 'show': show,
            'season': 1, 'episode': 1, 'direct_ok': direct}


CAT = {'items': {i['id']: i for i in [item('a', 22), item('b', 22, False), item('c', 3), item('d', 200),
                                      item('ad1', 1, show='Ads'), item('x', 22, title='Funny Bit')]}}
GROUPS = {'g1': {'item_ids': ['a', 'b', 'c', 'd', 'x']}, 'ads': {'item_ids': ['ad1']}}


class T(unittest.TestCase):
    def test_filters(self):
        self.assertEqual(pool_items(CAT, GROUPS, {'groups': ['g1']}), ['a', 'b', 'c', 'd', 'x'])
        self.assertEqual(pool_items(CAT, GROUPS, {'groups': ['g1'], 'filters': {'min_min': 5, 'max_min': 100}}), ['a', 'b', 'x'])
        self.assertEqual(pool_items(CAT, GROUPS, {'groups': ['g1'], 'filters': {'allow_transcode': False, 'min_min': 5, 'max_min': 100}}), ['a', 'x'])
        self.assertEqual(pool_items(CAT, GROUPS, {'groups': ['g1'], 'filters': {'contains': 'funny, nothing'}}), ['x'])

    def test_items_added_once(self):
        self.assertEqual(pool_items(CAT, GROUPS, {'groups': ['g1'], 'items': ['a', 'ad1']}), ['a', 'b', 'c', 'd', 'x', 'ad1'])

    def test_hidden_items_are_left_out_everywhere(self):
        self.assertEqual(pool_items(CAT, GROUPS, {'groups': ['g1'], 'items': ['ad1']}, hidden={'b', 'ad1'}), ['a', 'c', 'd', 'x'])
        spec = {'channels': [{'number': 3, 'name': 'T', 'pools': [{'name': 'shows', 'groups': ['g1']}], 'dayparts': []}]}
        _, items, stats = compile_all(spec, CAT, GROUPS, {'a', 'b'})
        self.assertEqual(sorted(i['id'] for i in items), ['c', 'd', 'x'])
        self.assertEqual(stats[3]['shows']['items'], 3)

    def test_a_custom_list_is_just_a_group(self):
        groups = dict(GROUPS, **{'my:1': {'id': 'my:1', 'type': 'list', 'item_ids': ['x', 'ad1']}})
        self.assertEqual(pool_items(CAT, groups, {'groups': ['my:1']}), ['x', 'ad1'])

    def test_compile(self):
        spec = {'channels': [{'number': 3, 'name': 'T', 'pools': [{'name': 'shows', 'groups': ['g1'], 'filters': {'min_min': 5, 'max_min': 100}}],
                              'commercials': {'groups': ['ads']}, 'dayparts': []}]}
        chans, items, stats = compile_all(spec, CAT, GROUPS)
        self.assertEqual(chans[0].commercial_pool, '_ads')
        self.assertEqual(chans[0].dayparts[0].pools, ['shows'])         # default: all day
        self.assertEqual(sorted(i['id'] for i in items), ['a', 'ad1', 'b', 'x'])
        self.assertEqual(stats[3]['shows'], {'items': 3, 'hours': 1.1, 'direct': 2})


if __name__ == '__main__':
    unittest.main()
