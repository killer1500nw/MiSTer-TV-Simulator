# Changelog

## 0.7.1b (beta)

- **Fix: Jellyfin 12.** Jellyfin 12 turns off the old ways of sending an API key, so Studio's connection test answered HTTP 401 even with a valid key. The Jellyfin connection, password sign-in and playback now send the key in the `Authorization` header, and playback links no longer carry the key in the web address. It still works with Jellyfin 10.11. Thanks to scr512 for the report, the fix and the testing (issue #1, pull request #2).
- **Fix: the source repository was missing five small files** (`__init__.py` and `__main__.py` in `tvsim`, `tvsim/player` and `tvsim/studio`), so running Studio or the player from a fresh clone, or building the installer from one, did not work. Installer releases were not affected.
- **Fix: our player no longer interferes with other H.264 cores.** If you left our core and opened another one that uses the same decoder (the MisterZine Plex core, the YouTube player), our player could keep running for a while, write to the decoder, and then send the MiSTer back to the menu, throwing you out of the other core. The player now stops at once without touching the core when another core is loaded, never sends "go to menu" over another core, and the background starter ends it as a backstop. While our core is open, a YouTube CRT player that is also running is now stopped and started again when you leave, instead of staying stopped until the next reboot, so the YouTube player, the MisterZine Plex core and this one can all be used one after another. If some other program still holds the decoder when the player starts, the player now waits up to 10 seconds for it to let go, and if it gives up, the log names the program that is in the way. The background starter also uses far less CPU (about 0.4%, down from about 4%).

## 0.7b (beta)

- **Share channels between MiSTers.** On the first-run screen press A (or, in Studio, **Share with other MiSTers → Find other MiSTers**) to copy the channels, sign-ins and logos of another MiSTer in your home, using its four-digit code. The copy is kept up to date: every five minutes it asks the other MiSTer one small question and copies again only when something changed. Both then show the same programme at the same moment. Not yet tested on two real MiSTers.

## 0.6b (beta)

- TV guide themes: Satellite, Cable, Modern and Classic, chosen with Start in the guide or in Studio. Y shows a programme's details (episode, year, rating, length and the server's description, which needs a re-index to fetch). Channel and programme names wrap between words instead of being cut. The guide cursor now moves programme by programme, and L / R page through channels.
- Per-channel logo: upload a PNG in Studio; it shows in the bottom right corner all the time or for a short time after tuning or when a programme starts.
- **Other → MiSTer 90s TV** menu entry with a date code, like any core (the Scripts launcher is gone): the entry is a copy of the H.264 core named `MiSTer 90s TV_<date>.rbf`, and a background starter, added to `user-startup.sh` only with your consent, starts the player when it is chosen.
- Gamepads no longer rumble for about 30 seconds when they connect while the player runs.
- The installer builds the menu entry date from the build date, and the uninstaller removes the entry, the boot lines and the files.

## 0.5b (beta)

First public beta.

- Live TV channels built from Jellyfin and Plex libraries: a deterministic schedule on a 30/60 minute grid, with ad breaks (capped at 15 minutes, only when the slot has time left).
- Direct play on the FPGA for H.264 Main/High up to 720p30 / 480p60; server transcoding for everything else (Jellyfin and Plex).
- Seamless ad breaks: a programme, its ads and the next show play as one stream with no gap.
- On-screen channel banner, number entry, scrolling TV guide, picture shapes (Fit, Fill, 14:9, Zoom 16:9, Zoom 2.35, remembered per show) and channel-change static.
- Studio: a web page hosted on the MiSTer for adding sources, browsing, finding and hiding items, making lists, building channels and applying them to the TV. Protected by a four-digit code shown on the TV; Plex sign-in survives the page being closed.
- One-file installer with its own ffmpeg download (pinned SHA-256), optional download of the H.264 core, launcher and uninstaller.
- The player reloads the video core by itself if it stops answering.

Known limits: subtitles are not shown; stereo sound only; Plex transcodes take about 5 to 6 seconds to start when changing channel; tested on one MiSTer with an analog CRT, Jellyfin 10.11 and Plex 1.43.
