"""End-to-end smoke test: full pipeline produces a valid 30-second ringtone."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ringtone_forge import verify


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.requires_ffmpeg,
    pytest.mark.requires_real_audio,
]


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "ringtone_forge.cli", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


@pytest.mark.requires_torch
@pytest.mark.slow
def test_full_pipeline_with_stems(percussive_song_path, out_dir):
    """The whole agent: load → classify → stems analyze → align → trim →
    envelope → encode → verify. Run on war_drums.m4a (shortest sample, fastest).
    """
    out = out_dir / "e2e_ringtone.m4a"

    proc = _run_cli(str(percussive_song_path), str(out),
                    "--algo", "stems", "--device", "auto")
    # Verify may report warnings (some checks fail on non-pop sources) — accept those
    assert out.exists(), f"output not produced. stderr:\n{proc.stderr}"

    # 1. Hard requirements: file is a valid m4a with exactly 30 seconds
    duration_proc = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(out)
    ], capture_output=True, text=True)
    duration = float(duration_proc.stdout.strip())
    assert abs(duration - 30.0) < 0.05, f"duration {duration}s is not 30s"

    # 2. File should have audio stream + non-trivial size
    assert out.stat().st_size > 100_000, f"output too small ({out.stat().st_size} bytes)"

    # 3. Verify report should pass at least the hygiene checks (duration, peak, fade-out)
    report = verify.verify(
        out,
        preset_start_amp=0.20,  # percussive preset
        preset_rise_seconds=20.0,
        preset_sustain_seconds=7.0,
    )
    duration_check = next(c for c in report.checks if "duration" in c.name.lower())
    assert duration_check.passed
    fade_check = next(c for c in report.checks if "29.7" in c.name)
    assert fade_check.passed, f"fade-out failed: {fade_check.actual}"


def test_full_pipeline_features_only(vocal_song_path, out_dir):
    """No-PyTorch path — verify the heuristic algorithms still work end to end."""
    out = out_dir / "features_ringtone.m4a"

    proc = _run_cli(str(vocal_song_path), str(out),
                    "--algo", "features", "--start", "120")
    assert out.exists(), f"output not produced. stderr:\n{proc.stderr}"
    assert out.stat().st_size > 100_000

    duration_proc = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(out)
    ], capture_output=True, text=True)
    assert abs(float(duration_proc.stdout.strip()) - 30.0) < 0.05
