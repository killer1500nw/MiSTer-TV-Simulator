#!/bin/bash
# Remove MiSTer 90s TV Simulator: its program, its channels and sign-ins, its ffmpeg and the two scripts.
# Leaves the H.264 core (by owenb321) in /media/fat/_Other, which other programs may use.
D=/media/fat/Scripts/.config/MiSTer_90s_TV
H=/media/fat/MiSTer_90s_TV
echo "This removes MiSTer 90s TV Simulator, including your channels, lists and saved sign-ins:"
echo "  $D"
echo "  $H"
if [ "${1:-}" != "-y" ] && [ -t 0 ]; then
  read -r -p "Continue? [y/N] " ANSWER || ANSWER=n
  case "$ANSWER" in y|Y|yes|YES) ;; *) echo "Cancelled."; exit 0;; esac
fi
for p in $(ps | grep -v grep | grep -E "tvsim.player|tvsim.studio" | awk '{print $1}'); do kill -9 "$p" 2>/dev/null; done
rm -rf "$D" "$H" /media/fat/Scripts/MiSTer_90s_TV.sh
echo "Removed."
rm -f "$0"
[ -t 0 ] && read -r -p "Press Enter to return to MiSTer." _ || true
exit 0
