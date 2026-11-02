import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim import jfurl
from tvsim.model import Item

CFG = {'server': 'http://h:8096/jf/', 'api_key': 'K'}


class T(unittest.TestCase):
    def test_direct(self):
        url, seek = jfurl.stream(CFG, Item('jf:abc', 't', 60, direct_ok=True), 30, 's')
        self.assertTrue(url.startswith('http://h:8096/jf/Videos/abc/stream?'))
        self.assertIn('Static=true', url)
        self.assertEqual(seek, 30.0)

    def test_transcode_always_reencodes_and_starts_on_server(self):
        url, seek = jfurl.stream(CFG, Item('jf:abc', 't', 60, direct_ok=False), 30, 's')
        self.assertIn('stream.ts?', url)
        self.assertIn('AllowVideoStreamCopy=false', url)     # else a Baseline H.264 file is only re-wrapped and shows no picture
        self.assertIn('StartTimeTicks=300000000', url)
        self.assertEqual(seek, 0.0)


if __name__ == '__main__':
    unittest.main()
