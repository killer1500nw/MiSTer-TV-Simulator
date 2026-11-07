import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tvsim.jellyfin import Jellyfin, authenticate


TOKEN = 'test-api-token-not-a-real-credential'
USERNAME = 'test-user-not-a-real-credential'
PASSWORD = 'test-password-not-a-real-credential'
CLIENT_AUTH = ('MediaBrowser Client="MiSTer 90s TV Simulator", Device="PC", '
               'DeviceId="mister-90s-tv-studio", Version="1.0"')


def response(data):
    return io.BytesIO(json.dumps(data).encode('utf-8'))


def headers(request):
    # urllib normalizes header capitalization, so compare names case-insensitively.
    return {name.lower(): value for name, value in request.header_items()}


class JellyfinTest(unittest.TestCase):
    def assert_modern_auth(self, request, expected):
        actual = headers(request)
        self.assertEqual(actual.get('authorization'), expected)
        self.assertNotIn('x-emby-token', actual)
        self.assertNotIn('x-emby-authorization', actual)

    def test_get_url_headers_query_and_timeout(self):
        payload = {'Items': [{'Name': 'Example'}]}
        with patch('urllib.request.urlopen', return_value=response(payload)) as urlopen:
            result = Jellyfin('http://example.test:8096/jellyfin///', TOKEN, timeout=12).get(
                '/Items', SearchTerm='space & slash/é', Recursive=True,
                StartIndex=0, Empty='', Skip=None)

        self.assertEqual(result, payload)
        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(urlopen.call_args.kwargs, {'timeout': 12})
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        url = urlsplit(request.full_url)
        self.assertEqual((url.scheme, url.netloc, url.path),
                         ('http', 'example.test:8096', '/jellyfin/Items'))
        self.assertEqual(parse_qs(url.query, keep_blank_values=True), {
            'SearchTerm': ['space & slash/é'], 'Recursive': ['True'],
            'StartIndex': ['0'], 'Empty': [''],
        })
        self.assert_modern_auth(request, 'MediaBrowser Token="%s"' % TOKEN)
        self.assertNotIn(TOKEN, request.full_url)
        self.assertEqual(headers(request), {'authorization': 'MediaBrowser Token="%s"' % TOKEN})

    def test_get_without_query_and_default_timeout(self):
        with patch('urllib.request.urlopen', return_value=response({'ok': True})) as urlopen:
            self.assertEqual(Jellyfin('https://example.test/', TOKEN).get('/System/Info', ignored=None),
                             {'ok': True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://example.test/System/Info')
        self.assertEqual(urlopen.call_args.kwargs, {'timeout': 60})
        self.assert_modern_auth(request, 'MediaBrowser Token="%s"' % TOKEN)

    def test_libraries_and_playlist_items(self):
        with patch('urllib.request.urlopen', side_effect=[
            response([{'Name': 'Movies'}]), response({'Items': [{'Id': 'item-1'}]}),
            response({}),
        ]) as urlopen:
            client = Jellyfin('https://example.test/jf/', TOKEN)
            self.assertEqual(client.libraries(), [{'Name': 'Movies'}])
            self.assertEqual(client.playlist_items('playlist-1'), [{'Id': 'item-1'}])
            self.assertEqual(client.playlist_items('empty'), [])
        requests = [call.args[0] for call in urlopen.call_args_list]
        self.assertEqual([r.full_url for r in requests], [
            'https://example.test/jf/Library/VirtualFolders',
            'https://example.test/jf/Playlists/playlist-1/Items',
            'https://example.test/jf/Playlists/empty/Items',
        ])
        for request in requests:
            self.assert_modern_auth(request, 'MediaBrowser Token="%s"' % TOKEN)

    def test_items_paginate_until_total(self):
        pages = [
            {'Items': [{'Id': '1'}, {'Id': '2'}], 'TotalRecordCount': 3},
            {'Items': [{'Id': '3'}], 'TotalRecordCount': 3},
        ]
        with patch('urllib.request.urlopen', side_effect=[response(p) for p in pages]) as urlopen:
            items = list(Jellyfin('https://example.test/', TOKEN).items(
                page=2, ParentId='folder 1', Recursive=True))
        self.assertEqual(items, [{'Id': '1'}, {'Id': '2'}, {'Id': '3'}])
        self.assertEqual(urlopen.call_count, 2)
        for index, call in enumerate(urlopen.call_args_list):
            request = call.args[0]
            self.assertEqual(urlsplit(request.full_url).path, '/Items')
            self.assertEqual(parse_qs(urlsplit(request.full_url).query), {
                'StartIndex': [str(index * 2)], 'Limit': ['2'],
                'ParentId': ['folder 1'], 'Recursive': ['True'],
            })
            self.assert_modern_auth(request, 'MediaBrowser Token="%s"' % TOKEN)
            self.assertNotIn(TOKEN, request.full_url)

    def test_items_stop_on_empty_page_even_if_total_is_larger(self):
        with patch('urllib.request.urlopen', return_value=response(
                {'Items': [], 'TotalRecordCount': 10})) as urlopen:
            self.assertEqual(list(Jellyfin('https://example.test', TOKEN).items()), [])
        urlopen.assert_called_once()
        self.assertEqual(parse_qs(urlsplit(urlopen.call_args.args[0].full_url).query),
                         {'StartIndex': ['0'], 'Limit': ['500']})

    def test_login_request_and_token_parsing(self):
        with patch('urllib.request.urlopen', return_value=response({
            'AccessToken': TOKEN, 'User': {'Name': USERNAME}, 'Other': 'ignored',
        })) as urlopen:
            token = authenticate('https://example.test/jellyfin///', USERNAME, PASSWORD, timeout=7)

        self.assertEqual(token, TOKEN)
        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(urlopen.call_args.kwargs, {'timeout': 7})
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.full_url, 'https://example.test/jellyfin/Users/AuthenticateByName')
        self.assertEqual(json.loads(request.data.decode('utf-8')),
                         {'Username': USERNAME, 'Pw': PASSWORD})
        self.assert_modern_auth(request, CLIENT_AUTH)
        self.assertEqual(headers(request), {'content-type': 'application/json',
                                            'authorization': CLIENT_AUTH})
        for secret in (USERNAME, PASSWORD, TOKEN):
            self.assertNotIn(secret, request.full_url)
            self.assertNotIn(secret, str(headers(request)))
        self.assertNotIn(TOKEN, request.data.decode('utf-8'))

    def test_login_unicode_and_default_timeout(self):
        with patch('urllib.request.urlopen', return_value=response({'AccessToken': TOKEN})) as urlopen:
            self.assertEqual(authenticate('http://example.test/', 'user é', 'päss 🔑'), TOKEN)
        request = urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data.decode('utf-8')),
                         {'Username': 'user é', 'Pw': 'päss 🔑'})
        self.assertEqual(urlopen.call_args.kwargs, {'timeout': 30})
        self.assert_modern_auth(request, CLIENT_AUTH)

    def test_login_token_can_be_used_for_api_without_leaking_credentials(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch('urllib.request.urlopen', side_effect=[
            response({'AccessToken': TOKEN}), response({'Items': []}),
        ]) as urlopen, contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            token = authenticate('https://example.test/jf/', USERNAME, PASSWORD)
            self.assertEqual(Jellyfin('https://example.test/jf/', token).get('/Items'), {'Items': []})
        login, api = [call.args[0] for call in urlopen.call_args_list]
        self.assert_modern_auth(login, CLIENT_AUTH)
        self.assert_modern_auth(api, 'MediaBrowser Token="%s"' % TOKEN)
        for secret in (USERNAME, PASSWORD, TOKEN):
            self.assertNotIn(secret, login.full_url)
            self.assertNotIn(secret, api.full_url)
            self.assertNotIn(secret, output.getvalue())
            self.assertNotIn(secret, errors.getvalue())
        for secret in (USERNAME, PASSWORD):
            self.assertNotIn(secret, str(headers(api)))
            self.assertIsNone(api.data)

    def test_login_missing_token_and_invalid_json_raise(self):
        with patch('urllib.request.urlopen', return_value=response({'User': {}})):
            with self.assertRaises(KeyError):
                authenticate('https://example.test', USERNAME, PASSWORD)
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'not json')):
            with self.assertRaises(json.JSONDecodeError):
                authenticate('https://example.test', USERNAME, PASSWORD)

    def test_network_errors_propagate(self):
        with patch('urllib.request.urlopen', side_effect=URLError('unavailable')):
            with self.assertRaises(URLError):
                Jellyfin('https://example.test', TOKEN).get('/Items')
            with self.assertRaises(URLError):
                authenticate('https://example.test', USERNAME, PASSWORD)


if __name__ == '__main__':
    unittest.main()
