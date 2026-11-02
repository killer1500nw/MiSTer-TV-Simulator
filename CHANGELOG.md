# Changelog

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
