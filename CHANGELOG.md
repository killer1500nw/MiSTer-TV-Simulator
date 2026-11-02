# Changelog

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
