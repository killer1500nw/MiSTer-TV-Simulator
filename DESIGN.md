# MiSTer 90s TV Simulator — design

Name: **MiSTer 90s TV Simulator** (file names use `MiSTer_90s_TV`). A set-top-box style
"live TV" that builds channels from the user's Plex / Jellyfin library and plays
them on a CRT.

**A project of its own.** Own name, repo, installer and files on the card: `Scripts/MiSTer_90s_TV.sh`,
`Scripts/.config/MiSTer_90s_TV/` (app and config), `/media/fat/MiSTer_90s_TV/` (its own ffmpeg), its own log.
It does not install, start, restart or depend on any other player. When it exits it hands the screen back to
the MiSTer menu. The only contact with other software: only one program can feed the H.264 core at a time,
so a different player of that core that starts at boot is stopped (not restarted) while this one runs.
The video engine is owenb321's stock H.264 `.rbf`, which keeps his file name (renaming it would confuse
Downloader updates); only a future forked core would get its own `MiSTer_90s_TV_*.rbf` name (§8).
Some source files were copied from the author's earlier project; see NOTICE.md.

## 1. Key decision: no new FPGA core needed for v1

The three reference projects point the same way:

| Project | What it gives us | Use |
|---|---|---|
| owenb321/MiSTer_h264_decoder | FPGA H.264 decode + scan-out (480i/240p/HDMI), ring buffer in DDR, 48 kHz PCM audio. GPL-3.0 core, MIT client lib | **The video engine.** Reuse as-is. User installs it (download + SHA-256 check, same as MiSTer-YouTube's `Install_H264_Core.sh`) — we never bundle it. |
| matijaerceg/misterzine-plex-core, misterzine-jellyfin | Proof that Plex/Jellyfin → h264 core works; server transcodes anything the core can't take (≤720p, 0.4–8 Mbit/s) | **Reference only.** No stated licence, paid beta, "no extra rights from source availability" → do **not** copy code. We re-implement from the public API docs. |
| Our earlier MiSTer player (origin of copied code) | ring client, TS demuxer, feeder (A/V sync, pre-roll), framebuffer overlay idea | Copied into `tvsim/player/` and adapted; nothing is shared at run time. |

So "the core" = the stock H.264 core + a Python app on the ARM (a `Scripts/`
launcher script in Scripts/). A custom bitstream is only
worth it later for hardware extras (channel-change static, OSD planes) — see §8.

Core limits to design around: High/Main 8-bit 4:2:0, ≤1280x720; real-time at
720p30 / 480p60 (≤~8 Mbit/s); CAVLC only ≤4–5 Mbit/s; 720p60 and 1080p fall behind.

## 2. Split of work: PC does the heavy lifting, MiSTer stays light

Per the CPU rule (MiSTer ARM is ~10–20x slower than a PC; video playback wins):

```
 PC / NAS                                   MiSTer (ARM + H.264 core)
 ┌──────────────────────────┐               ┌───────────────────────────┐
 │ Studio (web GUI)      │  catalog.json │ tvsim player (Python)     │
 │  - sign in Plex/Jellyfin │  channels.json│  - scheduler (cheap)      │
 │  - index libraries       │ ─────────────▶│  - guide + OSD + remote   │
 │  - build channels, rules │  (HTTP pull   │  - fetch stream URL       │
 │  - probe: direct vs      │   or SD copy) │  - demux TS → ring client │
 │    transcode             │               │  - ffmpeg: audio → PCM    │
 │  - optional ffmpeg       │◀──────────────│                           │
 │    transcode service     │  media stream └───────────────────────────┘
 └──────────────────────────┘        ▲
 Plex / Jellyfin server  ────────────┘ (direct play or server transcode)
```

* **Studio** (PC, Python stdlib HTTP server + one HTML page, no install pain)
  does all indexing, probing and editing, and writes `catalog.json`
  (items + duration + codec facts + direct/transcode verdict) and
  `channels.json`. The MiSTer pulls them from Studio over HTTP (or you copy the
  files). The ARM never walks a 10,000-item library.
* **Player** (MiSTer) reads those two small files, runs the scheduler, and
  for each airing asks the server for a stream.

## 3. "FPGA decodes when possible, transcode when too intense"

Decided per item at index time by Studio (ffprobe data from the server API):

1. **Direct** — H.264 Main/High ≤720p, ≤30 fps (or ≤480p60), ≤8 Mbit/s,
   audio anything (ARM ffmpeg decodes audio → PCM, ~6% of one core
   as measured). Server remuxes to MPEG-TS; ARM only demuxes.
2. **Server transcode** — everything else (HEVC, MPEG-2/4, 1080p, 60 fps, DVD/AVI
   rips, too-high bitrate). Ask Plex/Jellyfin for H.264 ≤480p/720p30 at a capped
   bitrate: Jellyfin `/Videos/{id}/stream.ts` with `VideoCodec=h264&MaxWidth&VideoBitRate`;
   Plex `/video/:/transcode/universal/start` (or `.m3u8`). Seek via `StartTimeTicks`/`offset`.
3. **Studio ffmpeg fallback** — if the server can't transcode (no Pass/hardware, or
   files outside the library), Studio runs local ffmpeg (NVENC/QSV if present) and serves
   MPEG-TS on demand, same URL shape. Optional "pre-bake" mode renders a 480p30
   H.264 copy of the whole channel lineup to a folder for zero-latency tuning.

SD-friendly 4:3 target: scale to 640x480 (or 854x480), letterbox/14:9 handled
by the existing `h264sps.py` crop trick.

## 4. Scheduler = "live" TV (implemented, `tvsim/schedule.py`)

* Each (channel, date) is generated from a seed → MiSTer and Studio always agree;
  tuning in at 8:17 seeks 17 minutes into the show. No schedule file to sync.
* Programmes snap to a slot grid (30 min default); leftover time in the slot is
  filled with **commercials** (from a commercial pool) then a station-ident slate
  — that's the 90s feel and keeps start times on :00/:30.
* Dayparts pick eligible pools per time of day (cartoons Saturday morning, movies at night).
* Pool modes: `shuffle` (with no-repeat window) or `sequential` (series continue
  episode by episode across days).
* Tested: tiles the whole day, deterministic, sequential continuity, seek offsets.

Known limits to fix: sequential replay is O(days since `anchor`) — Studio sets the
anchor to the channel's creation date; later add a small checkpoint file so the MiSTer
never replays. Programmes crossing midnight are cut (acceptable; real stations did too).

## 5. Rules (Studio, per channel)

Name/number/logo text · source pools (whole library, collection, playlist, folder,
single show) · mode shuffle/sequential · dayparts · slot length · commercial pool
and break style · no-repeat window · content rating cap · min/max runtime ·
era filter (year range) · "marathon" blocks · movie night slot · channel 0/guide
ordering. Playlists/folders map directly: Plex playlists & collections, Jellyfin
playlists & collections/folders — all via each server's REST API.

## 6. Set-top-box UI (MiSTer, framebuffer overlay)

Reuse `h264link.py`'s overlay path and gamepad/keyboard input.

* **Channel up/down / digits** → on-screen number + name in a chunky blue-grey OSD
  font, "VCR+"-style info bar (title, time left).
* **Guide** (Prevue Channel style): grid of channels × half-hours, auto-scrolling when idle,
  d-pad scroll when focused; header clock; bottom ad strip. Also exposable as channel
  "0" that plays guide full-screen with a looping music bed.
* Channel-change transition: static/blue screen while the next stream pre-rolls
  (hides the 1–3 s core flush + pre-roll we measured). Next-channel (±1) pre-open for
  faster surfing is a later optimisation.
* 240p/288p vs 480i/576i per existing core options.

## 7. Phases

0. **Spike** — play one Jellyfin/Plex direct-play URL through the existing ring pipeline on the MiSTer.
1. Catalog + scheduler (scheduler done; add API clients + `catalog.json`).
2. Player: tune, seek-to-offset, advance to next airing seamlessly, ad/filler slates.
3. OSD + guide.
4. Studio web GUI (login, browse, drag into channels, rules, preview schedule).
5. Transcode paths (server params, then Studio ffmpeg fallback), probe verdicts.
6. Installer (single `Install_MiSTer_90s_TV.sh`, with its own ffmpeg download), docs, THIRD_PARTY_NOTICES.

## 8. Optional later: forked FPGA core
Hardware channel-change static, OSD/guide planes composed in the FPGA to save ARM
copies, instant 14:9. Would be a GPL-3.0 fork of owenb321's core (Quartus 17.0.2).
Not needed to prove the idea.

## 9. Risks / open questions
* Surf latency (core flush on each new session) — measure in the spike.
* Seeking in Plex/Jellyfin transcodes starts a new server job each time (a few seconds).
* Auth: Jellyfin Quick Connect / API key; Plex plex.tv/link token — Studio holds them; MiSTer gets
  only short-lived stream URLs/tokens (secrets are stripped from the log).
* Subtitles: skip in v1 (burn-in via server if wanted).
* Name/legal: keep clear of Plex/Jellyfin/"Prevue" trademarks in branding.
