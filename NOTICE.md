# Third-party code and downloads

MiSTer 90s TV Simulator is licensed under the GNU General Public Licence, version 2 (see `LICENSE`). It is not affiliated with
Plex, Jellyfin, the MiSTer project or any of the projects below, and claims no ownership of them.

## Code included in this program

| Files | Origin | Licence |
|---|---|---|
| `tvsim/player/h264ring.py`, `tsdemux.py`, `h264sps.py`, `h264feed.py` | the author's earlier MiSTer player (github.com/killer1500nw/MiSTer-YouTube), adapted | GPL-2.0 |
| `tvsim/player/font8x8.py` | Daniel Hepper's font8x8_basic | public domain |
| `cacert.pem` (installed next to the program, used to check https downloads and https servers) | Mozilla's CA store as converted by the curl project, https://curl.se/ca/cacert.pem (see `CERTIFICATES-NOTICE.txt`) | MPL-2.0 |

The ring-buffer client in `h264ring.py` follows the interface of owenb321's MiSTer H.264 core (its own client library is MIT licensed).
Not copied from, by design: the MisterZine Plex and Jellyfin projects (no licence granted for their source).

## Downloaded by the installer (not part of this program)

| What | From | Licence | Checked against |
|---|---|---|---|
| **H.264 core** `H264_20261014.rbf` (optional, asks first) | https://github.com/owenb321/MiSTer_h264_decoder/releases/tag/v1.1.0 | GPL-3.0-or-later (core), MIT (client library) | SHA-256 `0790a889...e1bdfb`, pinned in `install_setup.py` |
| **ffmpeg 7.0.2** static ARM build | https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1 (John Van Sickle's build) | GPLv3 (its licence and readme are installed beside it) | SHA-256 `64b115a1...c5172`, pinned in `install_setup.py` |

These are separate programs that this one starts, not libraries linked into it. Their source is available from the links above.

## Trademarks

Plex is a trademark of Plex, Inc. Jellyfin is a trademark of its owners. MiSTer is a project of its community. Show names and artwork
in your libraries belong to their owners; this program only reads their titles and plays the files you already own.
