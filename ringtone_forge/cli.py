"""
Command-line entry point — the agent that strings everything together.

Pipeline (default invocation):

    1. Load source audio (librosa)
    2. Classify it (vocal / melodic / percussive)
    3. Analyze it for the best 30-second window (T2 multi-feature by default)
    4. Snap the start to the nearest beat
    5. Trim 30 seconds, lossless (ffmpeg -c copy)
    6. Apply the genre-adaptive volume envelope (ffmpeg volume filter)
    7. Verify the output against the 7-point quality bar
    8. Print a concise report

Every step is overridable on the command line:

    ringtone-forge song.mp3                         # full agent
    ringtone-forge song.mp3 --algo loudness         # use T1
    ringtone-forge song.mp3 --algo structural       # use T3
    ringtone-forge song.mp3 --start 60              # skip detection
    ringtone-forge song.mp3 --preset percussive     # force envelope preset
    ringtone-forge song.mp3 --no-envelope           # raw 30s trim only
    ringtone-forge song.mp3 --analyze               # report only, no output
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

# Suppress librosa's audioread deprecation chatter on every CLI run.
warnings.filterwarnings("ignore")

# ANSI helpers — fall back to plain text when stdout is piped.
_ISATTY = sys.stdout.isatty()
def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ISATTY else text
def _bold(s: str) -> str:   return _c("1", s)
def _green(s: str) -> str:  return _c("32", s)
def _red(s: str) -> str:    return _c("31", s)
def _yellow(s: str) -> str: return _c("33", s)
def _dim(s: str) -> str:    return _c("2", s)


def _check_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        sys.exit("ringtone-forge: ffmpeg not found in PATH. Install via Homebrew: brew install ffmpeg")


def _trim_and_envelope(
    src: Path,
    dst: Path,
    start: float,
    duration: float,
    envelope_filter: str | None,
) -> None:
    """Run ffmpeg to trim ``duration`` seconds at ``start`` and optionally apply an envelope."""
    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
                      "-ss", f"{start:.3f}",
                      "-i", str(src),
                      "-t", f"{duration:.3f}",
                      "-vn",          # ignore embedded artwork (mp3 cover, etc.)
                      "-map", "0:a:0"]  # take the first audio stream only
    if envelope_filter:
        cmd += ["-af", envelope_filter, "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-c:a", "copy"]
    cmd.append(str(dst))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"ringtone-forge: ffmpeg failed.\n{proc.stderr}")


def _format_seconds(s: float) -> str:
    m, s = divmod(int(s + 0.5), 60)
    return f"{m}:{s:02d}"


def _measure_source_lufs(src: Path) -> float | None:
    """Quick integrated-loudness probe of the whole source.

    Returns None if ffmpeg cannot determine the value (e.g. malformed file).
    Used as the reference for the source-integrity check in verify.
    """
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src),
         "-af", "ebur128=peak=true",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    import re as _re
    for line in (proc.stderr or "").splitlines():
        m = _re.match(r"\s+I:\s+(-?\d+\.\d+)\s+LUFS", line)
        if m:
            return float(m.group(1))
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ringtone-forge",
        description="Forge a 30-second ringtone from any audio source — intelligent, agent-style.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  ringtone-forge song.mp3
  ringtone-forge song.mp3 my_ringtone.m4a
  ringtone-forge song.mp3 --algo structural --preset vocal
  ringtone-forge song.mp3 --start 96 --no-beat-align
  ringtone-forge song.mp3 --analyze
""",
    )
    parser.add_argument("input", help="path to source audio (mp3, m4a, wav, flac, ogg)")
    parser.add_argument("output", nargs="?", default=None,
                        help="output path (default: <input>_ringtone.m4a)")
    parser.add_argument("--algo", choices=["loudness", "features", "structural"],
                        default="features",
                        help="window-selection algorithm (default: features)")
    parser.add_argument("--preset", choices=["vocal", "melodic", "percussive", "auto"],
                        default="auto",
                        help="envelope preset (default: auto = pick from classifier)")
    parser.add_argument("--start", type=float, default=None,
                        help="manually specify start time in seconds (overrides analysis)")
    parser.add_argument("--no-beat-align", action="store_true",
                        help="do not snap start to nearest beat")
    parser.add_argument("--no-envelope", action="store_true",
                        help="skip envelope, output raw 30s trim")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the 7-point quality verification at the end")
    parser.add_argument("--analyze", action="store_true",
                        help="only print analysis, don't write a file")
    parser.add_argument("--top-k", type=int, default=5,
                        help="how many candidate windows to report (default: 5)")
    parser.add_argument("--json", action="store_true",
                        help="emit a JSON report instead of human-readable output")
    parser.add_argument("--quiet", action="store_true", help="suppress non-essential output")

    args = parser.parse_args()
    _check_ffmpeg()

    src = Path(args.input).expanduser().resolve()
    if not src.is_file():
        sys.exit(f"ringtone-forge: input not found: {src}")

    if args.output is None:
        out_path = src.parent / f"{src.stem}_ringtone.m4a"
    else:
        out_path = Path(args.output).expanduser().resolve()
        # If user gave a directory, place the file inside it.
        if out_path.is_dir():
            out_path = out_path / f"{src.stem}_ringtone.m4a"

    # --- Step 1: load -----------------------------------------------------
    if not args.quiet:
        print(_bold(f"→ Forging {src.name}"))
        print(_dim(f"  output: {out_path}"))

    import librosa
    y, sr = librosa.load(str(src), sr=22050, mono=True)
    duration = len(y) / sr
    if not args.quiet:
        print(_dim(f"  loaded: {duration:.1f}s ({_format_seconds(duration)}) at {sr} Hz"))

    if duration < 30.0:
        sys.exit(f"ringtone-forge: source is only {duration:.1f}s — need at least 30s.")

    # --- Step 2: classify -------------------------------------------------
    from ringtone_forge.classifier import classify
    cls = classify(y, sr)
    if not args.quiet:
        print(f"  classifier: {_bold(cls.audio_type)}  "
              f"confidence={cls.confidence:.2f}  "
              f"({_dim(f'mfcc_var={cls.mfcc_variance:.1f} chroma_std={cls.chroma_std:.3f} onset/s={cls.onset_rate:.2f}')})")

    # --- Step 3: analyze (or honour --start) -----------------------------
    if args.start is not None:
        start_seconds = float(args.start)
        if not args.quiet:
            print(f"  start: {_bold(f'{start_seconds:.1f}s')} (manual)")
        candidates_for_report: list = []
    else:
        from ringtone_forge.analyzer import analyze
        candidates = analyze(y, sr,
                             algorithm=args.algo,
                             audio_type=cls.audio_type,
                             window_seconds=30.0,
                             top_k=args.top_k)
        candidates_for_report = candidates
        if not candidates:
            sys.exit("ringtone-forge: analyzer produced no candidates")
        start_seconds = candidates[0].start_seconds
        if not args.quiet:
            print(f"  algorithm: {args.algo}  → top start = {_bold(f'{start_seconds:.1f}s')}  "
                  f"({_format_seconds(start_seconds)})")
            for rank, c in enumerate(candidates[:args.top_k], 1):
                marker = "→" if rank == 1 else " "
                feat_summary = ", ".join(f"{k}={v}" for k, v in c.features.items() if k != "audio_type")
                print(_dim(f"   {marker} #{rank}: start={c.start_seconds:6.1f}s ({_format_seconds(c.start_seconds)})  "
                           f"score={c.score:.3f}  {feat_summary}"))

    # --- Step 4: beat-align ----------------------------------------------
    if not args.no_beat_align and args.start is None:
        from ringtone_forge.analyzer import align_to_beat
        aligned = align_to_beat(start_seconds, y, sr, max_drift=1.0)
        if abs(aligned - start_seconds) > 0.01 and not args.quiet:
            print(_dim(f"  beat-aligned: {start_seconds:.2f}s → {aligned:.2f}s"))
        start_seconds = aligned

    # Make sure we have 30s of source from the chosen start.
    if start_seconds + 30.0 > duration:
        start_seconds = max(0.0, duration - 30.0)
        if not args.quiet:
            print(_yellow(f"  start clamped to {start_seconds:.2f}s (would have run past EOF)"))

    # --- Pick envelope preset --------------------------------------------
    from ringtone_forge.envelope import get_preset, build_filter_expression, render_ascii
    preset_name = args.preset if args.preset != "auto" else cls.audio_type
    preset = get_preset(preset_name)
    if not args.quiet:
        print(f"  envelope: {_bold(preset.name)}  "
              f"(rise {preset.rise_seconds:g}s exp + sustain {preset.sustain_seconds:g}s + drop {preset.drop_seconds:g}s)")

    # --- Step 5: --analyze short-circuits here ---------------------------
    if args.analyze:
        if args.json:
            payload = {
                "source": str(src),
                "duration": round(duration, 2),
                "classification": cls.__dict__,
                "algorithm": args.algo,
                "candidates": [
                    {"start_seconds": round(c.start_seconds, 2),
                     "score": round(c.score, 3),
                     "features": c.features}
                    for c in candidates_for_report
                ],
                "preset": preset.__dict__ | {"total_seconds": preset.total_seconds},
                "would_trim_at": round(start_seconds, 2),
                "would_trim_to": round(start_seconds + 30.0, 2),
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print()
            print(render_ascii(preset))
            print()
            print(_dim("  (--analyze: no file written)"))
        return

    # --- Step 6: trim + envelope -----------------------------------------
    envelope_filter = None if args.no_envelope else build_filter_expression(preset)
    _trim_and_envelope(src, out_path, start_seconds, 30.0, envelope_filter)

    if not args.quiet:
        size = out_path.stat().st_size
        print(_green(f"✓ wrote {out_path.name} ({size/1024:.0f} KB)"))

    # --- Step 7: verify ---------------------------------------------------
    if args.no_verify or args.no_envelope:
        return

    from ringtone_forge.verify import verify
    # Source-integrity check needs the original LUFS — measure it lightly.
    src_lufs = _measure_source_lufs(src)
    report = verify(
        out_path,
        preset_start_amp=preset.start_amp,
        preset_rise_seconds=preset.rise_seconds,
        preset_sustain_seconds=preset.sustain_seconds,
        source_lufs=src_lufs,
    )
    if not args.quiet:
        print()
        print(_bold("Verification (preset-aware quality bar):"))
        for c in report.checks:
            mark = _green("✓") if c.passed else _red("✗")
            print(f"  {mark} {c.name:<54} {c.actual}")
        if report.all_passed:
            print(_green("\n✓ all checks passed."))
        else:
            print(_yellow(f"\n⚠ {report.failures} check(s) failed — review above."))
            sys.exit(report.failures)


if __name__ == "__main__":
    main()
