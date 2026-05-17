#!/usr/bin/env bash
# make-ringtone.sh — forge a 30-second ringtone from any audio source.
#
# Usage:
#   make-ringtone.sh <input> [<output>]
#
# Recipe (see ../METHODOLOGY.md for the reasoning):
#   0–20s : v(t) = 0.2 · 5^(t/20)        (exponential rise, dB-linear)
#   20–27s: v(t) = 1.0                   (sustain)
#   27–30s: v(t) = max(0, 1 − (t−27)/3)  (linear sharp drop)
#
# Output is always exactly 30.000 seconds, AAC 128 kbps in an .m4a container.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    cat <<'USAGE' >&2
make-ringtone.sh: forge a 30-second ringtone

Usage:
    make-ringtone.sh <input> [<output>]

Examples:
    make-ringtone.sh war_drums.m4a
    make-ringtone.sh raw.wav my_ringtone.m4a
USAGE
    exit 64
fi

INPUT="$1"
OUTPUT="${2:-${INPUT%.*}_ringtone.m4a}"

if [[ ! -f "$INPUT" ]]; then
    echo "make-ringtone.sh: input file not found: $INPUT" >&2
    exit 66
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "make-ringtone.sh: ffmpeg not found. Install via 'brew install ffmpeg' or your package manager." >&2
    exit 69
fi

# Check source duration is at least 30 seconds.
SRC_DURATION=$(ffprobe -v error -show_entries format=duration \
                       -of default=noprint_wrappers=1:nokey=1 "$INPUT")
if (( $(echo "$SRC_DURATION < 30" | bc -l) )); then
    printf "make-ringtone.sh: input is only %.2fs (need >= 30s)\n" "$SRC_DURATION" >&2
    exit 65
fi

echo "→ Forging $INPUT  →  $OUTPUT"
echo "  source duration: ${SRC_DURATION}s, taking first 30s"

ffmpeg -y -hide_banner -loglevel warning \
    -i "$INPUT" \
    -t 30 \
    -af "volume='if(lt(t,20), 0.2*pow(5,t/20), if(lt(t,27), 1, max(0, 1-(t-27)/3)))':eval=frame" \
    -c:a aac -b:a 128k \
    "$OUTPUT"

OUT_DURATION=$(ffprobe -v error -show_entries format=duration \
                       -of default=noprint_wrappers=1:nokey=1 "$OUTPUT")
OUT_SIZE=$(ls -lh "$OUTPUT" | awk '{print $5}')

printf "✓ Done. %s  (%.3fs, %s)\n" "$OUTPUT" "$OUT_DURATION" "$OUT_SIZE"
echo "  Verify with: ./scripts/verify-ringtone.sh \"$OUTPUT\""
