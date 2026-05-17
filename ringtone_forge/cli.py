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
        # Even without envelope, transcode to AAC so any input format
        # (mp3, flac, wav, m4a) lands cleanly in the .m4a container.
        # Stream-copy would fail when the source codec doesn't match the
        # output container (e.g. mp3 → .m4a is rejected by the ipod muxer).
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd.append(str(dst))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"ringtone-forge: ffmpeg failed.\n{proc.stderr}")


def _format_seconds(s: float) -> str:
    m, s = divmod(int(s + 0.5), 60)
    return f"{m}:{s:02d}"


def _doctor() -> int:
    """Print an environment-and-capability report for ringtone-forge.

    Returns an exit code: 0 if everything looks operational, non-zero if
    something critical is missing.
    """
    import platform as _platform
    import shutil as _shutil

    ok = _green if _ISATTY else (lambda s: s)
    bad = _red if _ISATTY else (lambda s: s)
    warn = _yellow if _ISATTY else (lambda s: s)
    bold = _bold if _ISATTY else (lambda s: s)
    dim = _dim if _ISATTY else (lambda s: s)

    print(bold("ringtone-forge — environment doctor"))
    print()

    # System info
    sysname = _platform.system()
    machine = _platform.machine()
    pyver = _platform.python_version()
    print(f"  System:   {sysname} ({machine})")
    print(f"  Python:   {pyver}")
    try:
        from ringtone_forge import __version__ as _v
        print(f"  ringtone-forge: {_v}")
    except Exception:
        print(dim("  ringtone-forge: import failed"))

    # External tools
    print()
    print(bold("External tools:"))
    has_ffmpeg = _shutil.which("ffmpeg") is not None
    has_ffprobe = _shutil.which("ffprobe") is not None
    print(f"  ffmpeg:   {ok('✓ available') if has_ffmpeg else bad('✗ MISSING — install via brew install ffmpeg')}")
    print(f"  ffprobe:  {ok('✓ available') if has_ffprobe else bad('✗ MISSING')}")
    has_uv = _shutil.which("uv") is not None
    print(f"  uv:       {ok('✓ available') if has_uv else dim('✗ not found (only needed for uv run)')}")

    # Optional Python deps
    print()
    print(bold("Python deps (baseline):"))
    for dep in ("librosa", "numpy", "scipy", "soundfile"):
        try:
            mod = __import__(dep)
            ver = getattr(mod, "__version__", "?")
            print(f"  {dep:<12} {ok(f'✓ {ver}')}")
        except ImportError:
            print(f"  {dep:<12} {bad('✗ MISSING — uv sync')}")

    print()
    print(bold("Python deps (optional [deep]):"))
    has_torch = False
    has_demucs = False
    try:
        import torch as _torch
        has_torch = True
        print(f"  {'torch':<12} {ok(f'✓ {_torch.__version__}')}")
    except ImportError:
        print(f"  {'torch':<12} {warn('— not installed (uv sync --extra deep adds it)')}")
    try:
        import demucs as _d
        has_demucs = True
        print(f"  {'demucs':<12} {ok('✓ installed')}")
    except ImportError:
        print(f"  {'demucs':<12} {warn('— not installed')}")

    # Backends
    print()
    print(bold("Hardware backends:"))
    if has_torch:
        mps_avail = _torch.backends.mps.is_available() and _torch.backends.mps.is_built()
        cuda_avail = _torch.cuda.is_available()
        print(f"  MPS (Apple GPU):  {ok('✓ available') if mps_avail else dim('— not available')}")
        if cuda_avail:
            gpu_name = _torch.cuda.get_device_name(0)
            print(f"  CUDA (NVIDIA):    {ok(f'✓ available — {gpu_name}')}")
        else:
            print(f"  CUDA (NVIDIA):    {dim('— not available')}")
        print(f"  CPU:              {ok('✓ always')}")
    else:
        print(f"  MPS / CUDA:       {dim('— PyTorch not installed; only CPU heuristics available')}")
        print(f"  CPU:              {ok('✓ always')}")

    # Algorithms
    print()
    print(bold("Available algorithms:"))
    print(f"  loudness    {ok('✓')} — RMS-max sliding window")
    print(f"  features    {ok('✓')} — multi-feature heuristic (default fallback)")
    print(f"  structural  {ok('✓')} — chroma SSM chorus detection")
    if has_torch and has_demucs:
        print(f"  stems       {ok('✓')} — demucs source separation + vocal-aware (default)")
    else:
        print(f"  stems       {warn('— uv sync --extra deep enables this')}")

    # Recommendation
    print()
    print(bold("Recommended for this environment:"))
    if has_torch and has_demucs:
        if has_torch and _torch.backends.mps.is_available():
            print(f"  {ok('--algo stems --device auto')} → uses MPS")
        elif has_torch and _torch.cuda.is_available():
            print(f"  {ok('--algo stems --device auto')} → uses CUDA")
        else:
            print(f"  {ok('--algo stems --device cpu')} → demucs on CPU (slower, ~30-50s/song)")
    else:
        print(f"  {ok('--algo features')} → librosa heuristics (fast, no GPU needed)")

    # Final status
    print()
    if not (has_ffmpeg and has_ffprobe):
        print(bad("⚠ ffmpeg is required and missing. Install before using ringtone-forge."))
        return 2
    if not has_torch:
        print(warn("ℹ Baseline only. For best chorus detection, install [deep] extras."))
    print(ok("✓ ready to forge."))
    return 0


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
    # --doctor is a special early-exit flag (no input file needed)
    if len(sys.argv) >= 2 and sys.argv[1] in ("--doctor", "doctor"):
        sys.exit(_doctor())

    parser = argparse.ArgumentParser(
        prog="ringtone-forge",
        description="Forge a 30-second ringtone from any audio source — intelligent, agent-style.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  ringtone-forge --doctor                       # check environment + recommend config
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
    parser.add_argument("--algo", choices=["loudness", "features", "structural", "stems", "auto"],
                        default="auto",
                        help="window-selection algorithm. 'auto' picks 'stems' if [deep] extras "
                             "are installed, otherwise 'features'. 'stems' uses demucs source "
                             "separation + vocal-aware chorus detection (most accurate).")
    parser.add_argument("--device", choices=["auto", "mps", "cuda", "cpu"], default="auto",
                        help="hardware backend for the deep model (only used by --algo stems). "
                             "'auto' picks MPS on Apple Silicon, then CUDA, then CPU.")
    parser.add_argument("--preset", choices=["vocal", "melodic", "percussive", "auto"],
                        default="auto",
                        help="envelope preset (default: auto = pick from classifier)")
    parser.add_argument("--start", type=float, default=None,
                        help="manually specify start time in seconds (overrides analysis)")
    parser.add_argument("--no-beat-align", action="store_true",
                        help="do not snap start to nearest beat")
    parser.add_argument("--no-chorus-align", action="store_true",
                        help="do not align chorus center to envelope sustain center "
                             "(only relevant when --algo stems is active)")
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

    # ─── Envelope parameter overrides (any of these overrides the preset default) ───
    env_grp = parser.add_argument_group("envelope overrides",
        description="override individual envelope parameters (otherwise preset defaults are used)")
    env_grp.add_argument("--rise", type=float, default=None,
                         help="rise duration in seconds (default: per-preset)")
    env_grp.add_argument("--sustain", type=float, default=None,
                         help="sustain duration in seconds (default: per-preset)")
    env_grp.add_argument("--drop", type=float, default=None,
                         help="drop duration in seconds (default: per-preset)")
    env_grp.add_argument("--start-amp", type=float, default=None,
                         help="start amplitude in (0, 1] (default: per-preset)")
    env_grp.add_argument("--duration", type=float, default=30.0,
                         help="total ringtone duration in seconds (default: 30)")

    # ─── LLM agent mode ──────────────────────────────────────────────────────
    llm_grp = parser.add_argument_group("LLM agent",
        description="let an LLM make tuning decisions (requires API key or local Ollama)")
    llm_grp.add_argument("--tune", type=str, default=None,
                         help='natural-language preference, e.g. "开头再轻一点"  (LLM translates to params)')
    llm_grp.add_argument("--agent", action="store_true",
                         help="full LLM-in-the-loop: tune → forge → verify → diagnose → retry (max 3)")
    llm_grp.add_argument("--llm", choices=["auto", "anthropic", "openai", "ollama", "mock"],
                         default="auto",
                         help="LLM backend (default: auto-detect best available)")
    llm_grp.add_argument("--max-retries", type=int, default=3,
                         help="max --agent retry attempts on verify failure (default: 3)")

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
        chorus_segment: tuple[float, float] | None = None
    else:
        # Resolve "auto" algorithm: prefer stems if torch+demucs installed
        algo = args.algo
        if algo == "auto":
            try:
                import torch  # noqa
                from demucs.pretrained import get_model  # noqa
                algo = "stems"
            except ImportError:
                algo = "features"

        chorus_segment = None
        if algo == "stems":
            # Deep stems-aware analysis
            if not args.quiet:
                print(f"  algorithm: {_bold('stems')} (demucs source separation, device={args.device})")
            try:
                from ringtone_forge.stems_analyzer import find_chorus_window_stems
                stem_result = find_chorus_window_stems(
                    str(src),
                    device=args.device,
                    top_k=args.top_k,
                )
                start_seconds = stem_result.chorus_start_seconds
                chorus_segment = (stem_result.chorus_start_seconds, stem_result.chorus_end_seconds)
                candidates_for_report = []
                if not args.quiet:
                    print(f"  primary stem: {stem_result.primary_stem}  "
                          f"device used: {stem_result.device_used}  "
                          f"separation: {stem_result.seconds_to_separate:.1f}s")
                    print(f"  detected chorus: "
                          f"{_bold(f'{stem_result.chorus_start_seconds:.1f}s')} → "
                          f"{stem_result.chorus_end_seconds:.1f}s  "
                          f"({_format_seconds(stem_result.chorus_start_seconds)} → "
                          f"{_format_seconds(stem_result.chorus_end_seconds)})  "
                          f"confidence={stem_result.confidence:.2f}")
                    for rank, (cstart, cscore) in enumerate(stem_result.candidates, 1):
                        marker = "→" if rank == 1 else " "
                        print(_dim(f"   {marker} #{rank}: start={cstart:6.1f}s ({_format_seconds(cstart)})  score={cscore:.3f}"))
            except ImportError as e:
                if not args.quiet:
                    print(_yellow(f"  [stems] unavailable ({e}), falling back to features"))
                algo = "features"

        if algo in ("loudness", "features", "structural"):
            from ringtone_forge.analyzer import analyze
            candidates = analyze(y, sr,
                                 algorithm=algo,
                                 audio_type=cls.audio_type,
                                 window_seconds=30.0,
                                 top_k=args.top_k)
            candidates_for_report = candidates
            if not candidates:
                sys.exit("ringtone-forge: analyzer produced no candidates")
            start_seconds = candidates[0].start_seconds
            if not args.quiet:
                print(f"  algorithm: {algo}  → top start = {_bold(f'{start_seconds:.1f}s')}  "
                      f"({_format_seconds(start_seconds)})")
                for rank, c in enumerate(candidates[:args.top_k], 1):
                    marker = "→" if rank == 1 else " "
                    feat_summary = ", ".join(f"{k}={v}" for k, v in c.features.items() if k != "audio_type")
                    print(_dim(f"   {marker} #{rank}: start={c.start_seconds:6.1f}s ({_format_seconds(c.start_seconds)})  "
                               f"score={c.score:.3f}  {feat_summary}"))

    # --- Pick envelope preset (must happen before chorus-align so we know sustain) -
    from ringtone_forge.envelope import (
        get_preset, build_filter_expression, render_ascii, resolve_envelope_params
    )
    preset_name = args.preset if args.preset != "auto" else cls.audio_type

    # Collect explicit envelope overrides from CLI flags.
    env_overrides = {
        "user_rise": args.rise,
        "user_sustain": args.sustain,
        "user_drop": args.drop,
        "user_start_amp": args.start_amp,
        "user_duration": args.duration if args.duration != 30.0 else None,
    }
    # Drop Nones for clean kwargs.
    env_overrides = {k: v for k, v in env_overrides.items() if v is not None}

    # --- LLM tune: natural language → params (only if --tune was given) ---
    llm_explanation = ""
    if args.tune:
        from ringtone_forge.llm_tuner import tune_from_preference
        if not args.quiet:
            print(_dim(f"  → calling LLM ({args.llm}) to interpret '{args.tune}' …"))
        tune_result = tune_from_preference(
            audio_type=cls.audio_type,
            user_preference=args.tune,
            duration=args.duration,
            classification_features={
                "mfcc_variance": cls.mfcc_variance,
                "chroma_std": cls.chroma_std,
                "onset_rate": cls.onset_rate,
                "zero_crossing_rate": cls.zero_crossing_rate,
            },
            backend=args.llm,
        )
        # LLM-suggested overrides take precedence over CLI flags only if CLI flag was unset.
        for k, v in tune_result.to_envelope_kwargs().items():
            env_overrides.setdefault(k, v)
        llm_explanation = tune_result.explanation
        if not args.quiet:
            print(f"  llm tune ({_bold(tune_result.backend)}): {tune_result.explanation}")

    preset = resolve_envelope_params(
        audio_type=preset_name,
        **env_overrides,
    )
    if not args.quiet:
        custom = "" if not env_overrides else _yellow(" [customised]")
        print(f"  envelope: {_bold(preset.name)}{custom}  "
              f"(rise {preset.rise_seconds:g}s exp + sustain {preset.sustain_seconds:g}s + drop {preset.drop_seconds:g}s)")

    # --- Step 3.5: chorus-aware envelope alignment -----------------------
    # If the analyzer told us where the chorus is, shift trim_start so that
    # the chorus midpoint lands on the envelope's sustain midpoint (the
    # loudest moment of the ringtone).
    if chorus_segment is not None and not args.no_chorus_align and args.start is None:
        from ringtone_forge.stems_analyzer import chorus_aware_trim_start
        aligned_start = chorus_aware_trim_start(
            chorus_start=chorus_segment[0],
            chorus_end=chorus_segment[1],
            preset_rise_seconds=preset.rise_seconds,
            preset_sustain_seconds=preset.sustain_seconds,
            source_duration=duration,
        )
        if abs(aligned_start - start_seconds) > 0.5 and not args.quiet:
            print(_dim(
                f"  chorus-aware align: {start_seconds:.1f}s → {aligned_start:.1f}s "
                f"(chorus mid {(chorus_segment[0]+chorus_segment[1])/2:.1f}s aligns to "
                f"envelope sustain mid)"
            ))
        start_seconds = aligned_start

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

    # --- Step 7: verify (with optional --agent retry loop) --------------
    if args.no_verify or args.no_envelope:
        return

    from ringtone_forge.verify import verify
    src_lufs = _measure_source_lufs(src)

    def _run_verify(preset_obj):
        return verify(
            out_path,
            preset_start_amp=preset_obj.start_amp,
            preset_rise_seconds=preset_obj.rise_seconds,
            preset_sustain_seconds=preset_obj.sustain_seconds,
            source_lufs=src_lufs,
        )

    def _print_report(rep):
        if args.quiet:
            return
        print()
        print(_bold("Verification (preset-aware quality bar):"))
        for c in rep.checks:
            mark = _green("✓") if c.passed else _red("✗")
            print(f"  {mark} {c.name:<54} {c.actual}")

    report = _run_verify(preset)
    _print_report(report)

    # --agent retry loop: LLM diagnose + adjust + re-forge
    attempts_left = args.max_retries if args.agent else 0
    while not report.all_passed and attempts_left > 0:
        if args.quiet:
            print(_yellow(f"\n⚠ {report.failures} check(s) failed — agent retrying ({args.max_retries - attempts_left + 1}/{args.max_retries}) …"))
        else:
            print(_yellow(f"\n⚠ {report.failures} check(s) failed — calling LLM ({args.llm}) to diagnose …"))

        from ringtone_forge.llm_tuner import diagnose_verify_failure
        failed_checks = [
            {"name": c.name, "actual": c.actual}
            for c in report.checks if not c.passed
        ]
        current_params = {
            "rise": preset.rise_seconds,
            "sustain": preset.sustain_seconds,
            "drop": preset.drop_seconds,
            "start_amp": preset.start_amp,
            "preset": preset.name,
        }
        diag = diagnose_verify_failure(failed_checks, current_params, backend=args.llm)

        if not args.quiet:
            print(f"  agent ({_bold(diag.backend)}): {diag.explanation}")

        # Merge diagnose suggestions into env_overrides and re-resolve preset.
        new_overrides = diag.to_envelope_kwargs()
        if not new_overrides:
            if not args.quiet:
                print(_dim("  (LLM had no concrete suggestion; stopping retry loop)"))
            break
        env_overrides.update(new_overrides)
        preset = resolve_envelope_params(audio_type=preset_name, **env_overrides)
        if not args.quiet:
            print(f"  retrying with envelope: rise={preset.rise_seconds:g}s "
                  f"sustain={preset.sustain_seconds:g}s drop={preset.drop_seconds:g}s "
                  f"start_amp={preset.start_amp:.2f}")

        # Re-forge with new params
        envelope_filter = build_filter_expression(preset)
        _trim_and_envelope(src, out_path, start_seconds, args.duration, envelope_filter)
        report = _run_verify(preset)
        _print_report(report)
        attempts_left -= 1

    if report.all_passed:
        if not args.quiet:
            print(_green("\n✓ all checks passed."))
    else:
        if not args.quiet:
            print(_yellow(f"\n⚠ {report.failures} check(s) failed — review above."))
        sys.exit(report.failures)


if __name__ == "__main__":
    main()
