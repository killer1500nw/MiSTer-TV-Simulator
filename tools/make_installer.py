"""Build release/Install_MiSTer_90s_TV.sh: one file to copy into the MiSTer's Scripts folder and run.

    python tools/make_installer.py

The program, the web page, the launcher and the setup code are packed inside the script (a gzip'd tar, base64 text after a
marker line); running it unpacks them to /tmp and runs install_setup.py, which downloads ffmpeg (and, if asked, the H.264 core)
with pinned checksums.
"""
import base64
import io
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = '__PAYLOAD_BELOW__'
HEADER = '''#!/bin/bash
# MiSTer 90s TV Simulator installer (version @VERSION@). Copy this file to the MiSTer's Scripts folder and run it from the menu,
# or over SSH:  bash Install_MiSTer_90s_TV.sh
# It needs the MiSTer to be online. Nothing outside /media/fat is touched.
set -u
T=/tmp/c90_install
rm -rf "$T"; mkdir -p "$T"
python3 - "$0" "$T" <<'PY' || { echo "Could not unpack the installer."; exit 1; }
import base64, io, sys, tarfile
raw = open(sys.argv[1], 'rb').read()
data = raw.split(b'\\n@MARK@\\n', 1)[1]
tarfile.open(fileobj=io.BytesIO(base64.b64decode(data)), mode='r:gz').extractall(sys.argv[2])
PY
python3 "$T/install_setup.py" "$@"
CODE=$?
rm -rf "$T"
[ -t 0 ] && read -r -p "Press Enter to return to MiSTer." _ || true
exit $CODE
@MARK@
'''.replace('@MARK@', MARK)


def add(tar, name, data, mode=0o644):
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), mode, 0
    tar.addfile(info, io.BytesIO(data))


def main():
    version = (ROOT / 'tvsim' / '__init__.py').read_text().split('"')[1]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz', compresslevel=9) as tar:
        for f in sorted((ROOT / 'tvsim').rglob('*')):
            if f.is_file() and f.suffix in ('.py', '.html') and '__pycache__' not in f.parts:
                add(tar, f.relative_to(ROOT).as_posix(), f.read_bytes())
        inst = ROOT / 'tools' / 'installer'
        for name in ('install_setup.py', 'MiSTer_90s_TV.sh', 'Uninstall_MiSTer_90s_TV.sh'):
            add(tar, name, (inst / name).read_bytes().replace(b'\r\n', b'\n'), 0o755)
        add(tar, 'cacert.pem', (ROOT / 'third_party' / 'certs' / 'cacert.pem').read_bytes())
        add(tar, 'CERTIFICATES-NOTICE.txt', (ROOT / 'third_party' / 'certs' / 'CERTIFICATES-NOTICE.txt').read_bytes())
        add(tar, 'NOTICE.md', (ROOT / 'NOTICE.md').read_bytes())
        add(tar, 'VERSION.txt', (version + '\n').encode())
    payload = base64.encodebytes(buf.getvalue())
    out = ROOT / 'release' / 'Install_MiSTer_90s_TV.sh'
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(HEADER.replace('@VERSION@', version).encode() + payload)
    print('%s: %.0f KB (payload %.0f KB)' % (out, out.stat().st_size / 1024, len(buf.getvalue()) / 1024))


if __name__ == '__main__':
    sys.exit(main())
