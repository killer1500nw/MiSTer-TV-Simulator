"""Before publishing: list what git would commit (everything .gitignore does not match) and look in those files for your own secrets
(API keys, Plex tokens) and home network addresses.

    python tools/check_repo.py [another-secret ...]
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), '..')


def main():
    os.chdir(ROOT)
    out = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], capture_output=True, text=True)
    if out.returncode:
        sys.exit('This needs git and a repository here (git init).')
    files = [f for f in out.stdout.split('\n') if f and os.path.isfile(f)]
    secrets = set()
    try:
        for s in json.load(open('studio/config.json', encoding='utf-8')).get('sources', []):
            secrets.update(v for k, v in s.items() if k in ('api_key', 'token') and v)
    except (OSError, ValueError):
        pass
    secrets.update(sys.argv[1:])                                  # any other secret to look for
    hits, addrs = [], []
    for f in files:
        text = open(f, encoding='utf-8', errors='ignore').read()
        hits += [(f, s[:4] + '...') for s in secrets if s in text]
        if re.search(r'192\.168\.4\.\d+', text):
            addrs.append(f)
    big = sorted(((os.path.getsize(f), f) for f in files), reverse=True)[:3]
    print('%d files would be committed' % len(files))
    print('secrets found in them:', hits or 'none')
    print('files naming your home addresses (192.168.4.x):', addrs or 'none')
    print('largest:', ', '.join('%s (%d KB)' % (f, s // 1024) for s, f in big))
    return 1 if hits else 0


if __name__ == '__main__':
    sys.exit(main())
