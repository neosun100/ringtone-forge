"""Integration tests — exercise the CLI as a subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.requires_ffmpeg]


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Invoke the CLI module as a subprocess so we test the real entry point."""
    cmd = [sys.executable, "-m", "ringtone_forge.cli", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


# --- --help -----------------------------------------------------------

class TestCLIHelp:
    def test_help_runs(self):
        proc = _run_cli("--help")
        assert proc.returncode == 0
        assert "ringtone-forge" in proc.stdout

    def test_help_lists_algos(self):
        proc = _run_cli("--help")
        for algo in ("loudness", "features", "structural", "stems", "auto"):
            assert algo in proc.stdout, f"algo '{algo}' not in help output"

    def test_help_lists_devices(self):
        proc = _run_cli("--help")
        for device in ("auto", "mps", "cuda", "cpu"):
            assert device in proc.stdout


# --- --analyze (no file written) --------------------------------------

@pytest.mark.requires_real_audio
class TestAnalyzeMode:
    def test_analyze_features_text(self, vocal_song_path):
        proc = _run_cli(str(vocal_song_path), "--analyze", "--algo", "features")
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert "classifier:" in proc.stdout
        # Should not have written a file
        assert "wrote" not in proc.stdout.lower()

    def test_analyze_json_is_parseable(self, vocal_song_path):
        proc = _run_cli(str(vocal_song_path), "--analyze", "--json", "--algo", "features", "--quiet")
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        # The non-quiet stdout should be just the JSON
        # Find the start of the JSON payload
        first_brace = proc.stdout.find("{")
        assert first_brace >= 0, "no JSON found in --analyze --json output"
        payload = json.loads(proc.stdout[first_brace:])
        assert "source" in payload
        assert "duration" in payload
        assert "classification" in payload
        assert "preset" in payload


# --- --no-envelope path (raw trim only) -------------------------------

@pytest.mark.requires_real_audio
class TestNoEnvelopeMode:
    def test_no_envelope_produces_30s_file(self, vocal_song_path, out_dir):
        out = out_dir / "raw.m4a"
        proc = _run_cli(str(vocal_song_path), str(out), "--no-envelope",
                        "--algo", "features", "--start", "30")
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert out.exists()
        # Check duration via ffprobe
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(out)
        ], capture_output=True, text=True)
        duration = float(result.stdout.strip())
        assert abs(duration - 30.0) < 0.1


# --- Full forge with --start (deterministic, no random analysis) ------

@pytest.mark.requires_real_audio
class TestFullForge:
    def test_forge_with_explicit_start_features(self, vocal_song_path, out_dir):
        out = out_dir / "ringtone.m4a"
        proc = _run_cli(str(vocal_song_path), str(out),
                        "--algo", "features", "--start", "120")
        assert proc.returncode in (0, 1, 2), f"stderr: {proc.stderr}"  # tolerate verify warnings
        assert out.exists(), f"output not written: {proc.stderr}"
        size = out.stat().st_size
        assert size > 100_000, f"output too small ({size} bytes)"


# --- Stem path (only if torch is installed) ---------------------------

@pytest.mark.requires_torch
@pytest.mark.requires_real_audio
@pytest.mark.slow
class TestStemAlgorithm:
    def test_stems_analyze_runs(self, vocal_song_path):
        proc = _run_cli(str(vocal_song_path), "--analyze", "--algo", "stems",
                        "--device", "auto")
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert "primary stem" in proc.stdout
        assert "detected chorus" in proc.stdout
