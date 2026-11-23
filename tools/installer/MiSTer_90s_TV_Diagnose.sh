#!/bin/bash
# MiSTer 90s TV Simulator: a report of what is installed and running, to send with a bug report.
# Secrets (API keys, tokens, Studio's code) are removed. The report is also saved as diagnostics.txt in the program folder.
D=/media/fat/Scripts/.config/MiSTer_90s_TV
if [ ! -d "$D/tvsim" ]; then echo "MiSTer 90s TV Simulator is not installed in $D"; [ -t 0 ] && read -r -p "Press Enter to return to MiSTer." _; exit 1; fi
cd "$D" && python3 -m tvsim.diagnose "$D"
echo
echo "Copy the text above, or open $D/diagnostics.txt (or Studio > Diagnostics in a browser)."
[ -t 0 ] && read -r -p "Press Enter to return to MiSTer." _ || true
exit 0
