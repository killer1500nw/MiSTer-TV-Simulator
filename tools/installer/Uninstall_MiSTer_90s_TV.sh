#!/bin/bash
# Remove MiSTer 90s TV Simulator: its program, its channels and sign-ins, its ffmpeg, the menu entry and the start-up line.
# Leaves the H.264 core (by owenb321) in /media/fat/_Other, which other programs may use.
D=/media/fat/Scripts/.config/MiSTer_90s_TV
H=/media/fat/MiSTer_90s_TV
echo "This removes MiSTer 90s TV Simulator, including your channels, lists and saved sign-ins:"
echo "  $D"
echo "  $H"
echo "  the menu entry Other > MiSTer 90s TV and its line in /media/fat/linux/user-startup.sh"
if [ "${1:-}" != "-y" ] && [ -t 0 ]; then
  read -r -p "Continue? [y/N] " ANSWER || ANSWER=n
  case "$ANSWER" in y|Y|yes|YES) ;; *) echo "Cancelled."; exit 0;; esac
fi
for p in $(ps | grep -v grep | grep -E "tvsim.daemon|tvsim.player|tvsim.studio" | awk '{print $1}'); do kill -9 "$p" 2>/dev/null; done
for p in $(ps | grep -v grep | grep -E "youtube_crt.py --daemon" | awk '{print $1}'); do kill -CONT "$p" 2>/dev/null; done   # (never leave the YouTube player held still)
if [ -f /media/fat/linux/user-startup.sh ]; then
  sed -i '/# BEGIN MiSTer 90s TV Simulator/,/# END MiSTer 90s TV Simulator/d' /media/fat/linux/user-startup.sh
fi
rm -f "/media/fat/_Other/MiSTer 90s TV.mgl" /media/fat/_Other/"MiSTer 90s TV"_*.rbf /media/fat/Scripts/MiSTer_90s_TV.sh
rm -rf "$D" "$H"
echo "Removed."
rm -f "$0"
[ -t 0 ] && read -r -p "Press Enter to return to MiSTer." _ || true
exit 0
