"""Build everything that goes on a GitHub release: the installer and its SHA-256 checksum.

    python tools/make_release.py

Writes release/Install_MiSTer_90s_TV.sh and release/SHA256SUMS.txt, and prints the tag to use (v<version>).
"""
import hashlib
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    try:
        runpy.run_path(str(ROOT / 'tools' / 'make_installer.py'), run_name='__main__')
    except SystemExit as exc:                          # make_installer exits when it is done; keep going unless it failed
        if exc.code not in (None, 0):
            raise
    version = (ROOT / 'tvsim' / '__init__.py').read_text().split('"')[1]
    installer = ROOT / 'release' / 'Install_MiSTer_90s_TV.sh'
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    (ROOT / 'release' / 'SHA256SUMS.txt').write_text('%s  %s\n' % (digest, installer.name), encoding='utf-8')
    print('version %s' % version)
    print('sha256  %s  %s' % (digest, installer.name))
    print('release tag: v%s   (mark the GitHub release as a pre-release)' % version)


if __name__ == '__main__':
    sys.exit(main())
