#!/usr/bin/env bash
# verify-ringtone.sh — measure a ringtone against the recipe's quality bar.
#
# Usage:
#   verify-ringtone.sh <ringtone.m4a>
#
# Checks (see ../METHODOLOGY.md §9):
#   1. duration is exactly 30.000s
#   2. true peak <= -1 dBFS (no clipping)
#   3. integrated loudness in [-16, -12] LUFS
#   4. LRA (loudness range) in [8, 14] LU
#   5. RMS at t=0s    < -25 dB  (rise origin is quiet enough)
#   6. RMS at t=15s   within 6 dB of climax (rise is reaching peak)
#   7. RMS at t=29.7s < -40 dB  (drop reaches near-silence)
#
# Output is a checklist with PASS/FAIL per item, and exit code = number of failures.

set -uo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: verify-ringtone.sh <ringtone.m4a>" >&2
    exit 64
fi

INPUT="$1"
[[ -f "$INPUT" ]] || { echo "verify-ringtone.sh: file not found: $INPUT" >&2; exit 66; }

FAILURES=0

# Helper: pretty-print a check.
check() {
    local label="$1" actual="$2" verdict="$3"
    if [[ "$verdict" == "PASS" ]]; then
        printf "  ✓ %-45s %s\n" "$label" "$actual"
    else
        printf "  ✗ %-45s %s  [FAIL: %s]\n" "$label" "$actual" "$verdict"
        FAILURES=$((FAILURES + 1))
    fi
}

# Helper: get RMS over a short window centered at $1 seconds.
rms_at() {
    local t="$1"
    ffmpeg -hide_banner -ss "$t" -t 0.5 -i "$INPUT" \
        -af "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level" \
        -f null - 2>&1 \
        | grep "RMS_level=" | tail -1 | awk -F= '{print $NF}'
}

echo "─────────────────────────────────────────────────────────────────"
echo "  Verifying: $INPUT"
echo "─────────────────────────────────────────────────────────────────"

# ---------- Duration ----------
DURATION=$(ffprobe -v error -show_entries format=duration \
                   -of default=noprint_wrappers=1:nokey=1 "$INPUT")
DUR_DELTA=$(echo "$DURATION - 30" | bc -l)
DUR_DELTA_ABS=$(echo "if ($DUR_DELTA < 0) -1*$DUR_DELTA else $DUR_DELTA" | bc -l)
if (( $(echo "$DUR_DELTA_ABS < 0.05" | bc -l) )); then
    check "duration" "${DURATION}s" "PASS"
else
    check "duration" "${DURATION}s (expected 30.000s)" "delta > 50ms"
fi

# ---------- EBU R128 metrics ----------
EBUR=$(ffmpeg -hide_banner -i "$INPUT" -af ebur128=peak=true -f null - 2>&1 | tail -25)

LUFS_I=$(echo "$EBUR" | grep -E "^\s*I:" | awk '{print $2}')
LRA=$(echo "$EBUR" | grep -E "^\s*LRA:" | head -1 | awk '{print $2}')
TPK=$(echo "$EBUR" | grep -E "^\s*Peak:" | awk '{print $2}')

# True peak: must be <= -1 dBFS
if [[ -n "$TPK" ]] && (( $(echo "$TPK <= -1" | bc -l) )); then
    check "true peak  ≤ −1 dBFS" "${TPK} dBFS" "PASS"
else
    check "true peak  ≤ −1 dBFS" "${TPK:-?} dBFS" "potential clipping"
fi

# Integrated loudness: -16 to -12 LUFS
if [[ -n "$LUFS_I" ]] && (( $(echo "$LUFS_I >= -16 && $LUFS_I <= -12" | bc -l) )); then
    check "integrated loudness  [−16, −12] LUFS" "${LUFS_I} LUFS" "PASS"
else
    check "integrated loudness  [−16, −12] LUFS" "${LUFS_I:-?} LUFS" "outside range"
fi

# LRA: 8 to 14 LU
if [[ -n "$LRA" ]] && (( $(echo "$LRA >= 8 && $LRA <= 14" | bc -l) )); then
    check "LRA (dynamic range)  [8, 14] LU" "${LRA} LU" "PASS"
else
    check "LRA (dynamic range)  [8, 14] LU" "${LRA:-?} LU" "outside range"
fi

# ---------- Time-domain RMS samples ----------
RMS_0=$(rms_at 0)
RMS_15=$(rms_at 15)
RMS_23=$(rms_at 23)   # mid-sustain, used as climax reference
RMS_END=$(rms_at 29.7)

# t=0s: should be < -25 dB
if [[ -n "$RMS_0" ]] && (( $(echo "$RMS_0 < -25" | bc -l) )); then
    check "RMS at t=0s   < −25 dB" "${RMS_0} dB" "PASS"
else
    check "RMS at t=0s   < −25 dB" "${RMS_0:-?} dB" "rise origin too loud"
fi

# t=15s: within 6 dB of climax (RMS_23)
if [[ -n "$RMS_15" && -n "$RMS_23" ]]; then
    DELTA=$(echo "$RMS_23 - $RMS_15" | bc -l)
    DELTA_ABS=$(echo "if ($DELTA < 0) -1*$DELTA else $DELTA" | bc -l)
    if (( $(echo "$DELTA_ABS <= 6" | bc -l) )); then
        check "RMS at t=15s within 6 dB of climax" "${RMS_15} dB (climax ${RMS_23} dB)" "PASS"
    else
        check "RMS at t=15s within 6 dB of climax" "${RMS_15} dB vs ${RMS_23} dB (Δ=${DELTA_ABS} dB)" "rise insufficient"
    fi
fi

# t=29.7s: should be < -40 dB
if [[ -n "$RMS_END" ]] && (( $(echo "$RMS_END < -40" | bc -l) )); then
    check "RMS at t=29.7s < −40 dB" "${RMS_END} dB" "PASS"
else
    check "RMS at t=29.7s < −40 dB" "${RMS_END:-?} dB" "drop incomplete"
fi

echo "─────────────────────────────────────────────────────────────────"
if [[ "$FAILURES" -eq 0 ]]; then
    echo "  ✓ All checks PASSED."
else
    echo "  ✗ $FAILURES check(s) FAILED."
fi
echo "─────────────────────────────────────────────────────────────────"

exit "$FAILURES"
