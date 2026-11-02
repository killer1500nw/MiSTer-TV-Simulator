#!/bin/bash
# MiSTer 90s TV Simulator: starts the web page (Studio) in the background and the player on the TV.
# The TV shows the address to open in a browser. When you leave the player (BACK twice) the MiSTer menu comes back.
D=/media/fat/Scripts/.config/MiSTer_90s_TV
kill_matching() {
  for p in $(ps | grep -v grep | grep -E "$1" | awk '{print $1}'); do kill -9 "$p" 2>/dev/null; done
}
# only one program at a time can feed the H.264 core: stop an earlier copy of this player, and any other player of that core
kill_matching "tvsim.player|youtube_crt.py --daemon"
# Studio (the web page) runs at low priority so it never competes with the picture; it stays up after you leave the player
if ! ps | grep -v grep | grep -q "tvsim.studio"; then
  if [ -f "$D/studio.log" ] && [ "$(wc -c < "$D/studio.log")" -gt 1000000 ]; then : > "$D/studio.log"; fi
  ( cd "$D" && C90_DATA="$D" nice -n 19 python3 -u -m tvsim.studio >> "$D/studio.log" 2>&1 </dev/null & )
fi
cd "$D" && exec python3 -u -m tvsim.player "$D" >/tmp/c90.out 2>&1
