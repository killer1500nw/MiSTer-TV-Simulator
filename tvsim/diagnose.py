"""A diagnostics report for bug reports: what is installed, what is running, what the MiSTer loaded, and the ends of the logs.

    python3 -m tvsim.diagnose [folder]        (the Scripts menu entry MiSTer_90s_TV_Diagnose does this, and Studio has a Diagnostics button)

Secrets are removed before anything is shown: API keys, Plex tokens, Studio's four-digit code. Network addresses stay (they are in
private ranges and are usually the clue), so look through the text before you post it somewhere public.
"""
import json
import os
import platform
import re
import shutil
import sys
import time

FOLDER = os.environ.get('C90_DATA') or '/media/fat/Scripts/.config/MiSTer_90s_TV'
HOME = '/media/fat/MiSTer_90s_TV'
OTHER = '/media/fat/_Other'
STARTUP = '/media/fat/linux/user-startup.sh'
MARK = 'MiSTer 90s TV Simulator'

_SECRET = re.compile(r'(?i)((?:api_?key|x-plex-token|token|pw|password)["\']?\s*[:=]\s*["\']?)[A-Za-z0-9_.\-]{6,}')
_QUOTED = re.compile(r'(?i)(Token=")[^"]+(")')
_CODE = re.compile(r'(?i)(\bcode\W{0,3})\d{4}\b')
_CODE_KEY = re.compile(r'("code"\s*:\s*")\d{4}(")')


def redact(text):
    """Remove API keys, tokens and Studio's code from a piece of text."""
    text = _SECRET.sub(r'\1***', text)
    text = _QUOTED.sub(r'\1***\2', text)
    text = _CODE_KEY.sub(r'\1****\2', text)
    return _CODE.sub(r'\1****', text)


def read(path, limit=200000):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read(limit)
    except OSError:
        return None


def tail(path, lines=30):
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 60000))
            data = f.read().decode('utf-8', 'replace')
    except OSError:
        return '(no such file: %s)' % path
    chunk = data.splitlines()[-lines:]
    return '\n'.join(chunk) if chunk else '(empty)'


def _processes():
    out = []
    try:
        for name in os.listdir('/proc'):
            if name.isdigit():
                try:
                    with open('/proc/%s/cmdline' % name, 'rb') as f:
                        args = [a.decode('utf-8', 'replace') for a in f.read().split(b'\0') if a]
                except OSError:
                    continue
                if args:
                    out.append((int(name), args))
    except OSError:
        pass
    return out


def _uptime():
    text = read('/proc/uptime')
    if not text:
        return 'unknown'
    secs = int(float(text.split()[0]))
    return '%dd %02d:%02d:%02d' % (secs // 86400, secs // 3600 % 24, secs // 60 % 60, secs % 60)


def _meminfo():
    text = read('/proc/meminfo') or ''
    got = dict(re.findall(r'^(MemTotal|MemAvailable):\s+(\d+) kB', text, re.M))
    return ', '.join('%s %d MB' % (k, int(v) // 1024) for k, v in sorted(got.items())) or 'unknown'


def section_system(folder):
    version = (read(os.path.join(folder, 'VERSION.txt')) or '?').strip()
    built = (read(os.path.join(folder, 'BUILD_DATE.txt')) or '?').strip()
    try:
        free = shutil.disk_usage(folder if os.path.isdir(folder) else '.').free // (1024 * 1024)
    except OSError:
        free = '?'
    return '\n'.join([
        'MiSTer 90s TV Simulator %s (built %s)' % (version, built),
        'report made: %s | uptime: %s | memory: %s | SD card free: %s MB' % (time.strftime('%Y-%m-%d %H:%M:%S'), _uptime(), _meminfo(), free),
        'Python %s | %s' % (sys.version.split()[0], ' '.join(platform.uname()[:1] + platform.uname()[2:3] + platform.uname()[4:5])),
    ])


def section_core():
    name = (read('/tmp/CORENAME') or '(no /tmp/CORENAME)').strip()
    procs = _processes()
    lines = ['core now: %r' % name]
    program = [(p, a) for p, a in procs if a[0].endswith('/MiSTer')]
    for pid, args in program:
        lines.append('MiSTer program (pid %d) was started with: %s' % (pid, ' | '.join(args[1:]) or '(nothing)'))
    if not program:
        lines.append('the MiSTer program was not found in the process list')
    ours = any(any('90s tv' in a.lower().replace('_', ' ') for a in args[1:]) for _, args in program)
    lines.append('loaded from our menu entry (Other > MiSTer 90s TV): %s' % ('yes' if ours else 'NO'))
    return '\n'.join(lines)


def section_processes():
    lines = []
    for pid, args in sorted(_processes()):
        text = ' '.join(args)
        if any(k in text for k in ('tvsim', 'youtube_crt', 'misterzine', 'zaparoo')) and 'diagnose' not in text:
            lines.append('%6d  %s' % (pid, text[:160]))
    return '\n'.join(lines) or '(none of ours, the YouTube player or MisterZine are running)'


def section_files(folder):
    lines = []
    for label, directory, pattern in (('_Other', OTHER, r'h264|90s|zine|youtube'),):
        try:
            names = sorted(n for n in os.listdir(directory) if re.search(pattern, n, re.I))
        except OSError:
            names = None
        if names is None:
            lines.append('%s: cannot read %s' % (label, directory))
        else:
            lines.append('%s: %s' % (label, ', '.join('%s (%d KB)' % (n, os.path.getsize(os.path.join(directory, n)) // 1024) for n in names) or '(none)'))
    try:
        found = sorted(n for n in os.listdir(HOME) if n.startswith('ffmpeg'))
    except OSError:
        found = []
    lines.append('ffmpeg in %s: %s' % (HOME, ', '.join(found) or 'MISSING'))
    startup = read(STARTUP)
    if startup is None:
        lines.append('%s: cannot read' % STARTUP)
    else:
        block = [l for l in startup.splitlines() if MARK in l or 'MiSTer_90s_TV' in l or 'tvsim' in l]
        lines.append('start-up line in user-startup.sh: %s' % ('present: ' + ' / '.join(block) if block else 'MISSING (the background starter does not start at boot)'))
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        entries = None
    lines.append('program folder %s: %s' % (folder, ', '.join(entries) if entries is not None else 'MISSING'))
    return '\n'.join(lines)


def section_setup(folder):
    lines = []
    for label, path in (('studio config', os.path.join(folder, 'studio', 'config.json')), ('player config', os.path.join(folder, 'config.json'))):
        text = read(path)
        if text is None:
            lines.append('%s: none yet' % label)
            continue
        try:
            data = json.loads(text)
            sources = data.get('sources', [])
            if isinstance(sources, dict):
                sources = [dict(v, id=k) for k, v in sources.items()]
            lines.append('%s: %s' % (label, '; '.join('%s %s %s (%s)' % (s.get('id'), s.get('type'), s.get('server'),
                                                                        'signed in' if (s.get('api_key') or s.get('token')) else 'NOT signed in')
                                                   for s in sources) or 'no sources'))
        except (ValueError, AttributeError):
            lines.append('%s: unreadable' % label)
    try:
        chans = json.loads(read(os.path.join(folder, 'channels.json')) or '{}').get('channels', [])
        lines.append('channels: %d (%s)' % (len(chans), ', '.join('%s %s' % (c.get('number'), c.get('name')) for c in chans[:12])))
    except (ValueError, AttributeError):
        lines.append('channels: none or unreadable')
    try:
        from . import netinfo
        lines.append('this MiSTer is at: %s' % (netinfo.studio_address() or 'no network address found'))
    except Exception as exc:                                 # (a report must never fail)
        lines.append('this MiSTer is at: unknown (%s)' % exc)
    return '\n'.join(lines)


def section_starter():
    text = read('/tmp/c90_daemon.json')
    if text is None:
        return 'no /tmp/c90_daemon.json: the background starter has not run since boot (or is an older version)'
    try:
        return 'last state written by the starter: %s' % json.dumps(json.loads(text))
    except ValueError:
        return 'unreadable'


def report(folder=None):
    folder = folder or FOLDER
    parts = [
        ('SYSTEM', lambda: section_system(folder)),
        ('CORE AND MENU ENTRY', section_core),
        ('RUNNING', section_processes),
        ('BACKGROUND STARTER', section_starter),
        ('INSTALLED FILES', lambda: section_files(folder)),
        ('SOURCES AND CHANNELS', lambda: section_setup(folder)),
        ('daemon.log (last 30 lines)', lambda: tail(os.path.join(folder, 'daemon.log'), 30)),
        ('log.txt: the player (last 40 lines)', lambda: tail(os.path.join(folder, 'log.txt'), 40)),
        ('studio.log (last 10 lines)', lambda: tail(os.path.join(folder, 'studio.log'), 10)),
        ('/tmp/c90.out: the player\'s console (last 30 lines)', lambda: tail('/tmp/c90.out', 30)),
        ('install.log (last 25 lines)', lambda: tail(os.path.join(folder, 'install.log'), 25)),
    ]
    out = ['=' * 70, 'MiSTer 90s TV Simulator diagnostics', '=' * 70]
    for title, fn in parts:
        try:
            body = fn()
        except Exception as exc:                             # one broken section must not hide the rest
            body = '(could not be read: %s: %s)' % (type(exc).__name__, exc)
        out += ['', '--- %s ---' % title, body]
    return redact('\n'.join(out)) + '\n'


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    folder = args[0] if args else None
    text = report(folder)
    print(text)
    target = os.path.join(folder or FOLDER, 'diagnostics.txt')
    try:
        with open(target, 'w', encoding='utf-8') as f:
            f.write(text)
        print('Also saved to %s' % target)
    except OSError:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
