#!/bin/bash
# MiSTer 90s TV Simulator: the background starter. Started at boot from /media/fat/linux/user-startup.sh.
# It waits for "Other > MiSTer 90s TV" to be chosen in the MiSTer menu and then starts the player.
D=/media/fat/Scripts/.config/MiSTer_90s_TV
if [ -f "$D/daemon.log" ] && [ "$(wc -c < "$D/daemon.log")" -gt 500000 ]; then : > "$D/daemon.log"; fi
cd "$D" && C90_DATA="$D" exec python3 -u -m tvsim.daemon >> "$D/daemon.log" 2>&1
