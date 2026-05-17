"""
Shared fixtures and environment detection for the ringtone-forge test suite.

Synthetic-audio fixtures are deterministic and fast — used by unit tests
that need a "song-like" signal but don't care about real musical content.
The real-audio fixtures point at the 5 songs in samples/source/ and are
used by regression and e2e tests.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest


# --------------------------------------------------------------------------
# Path fixtures
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = PROJECT_ROOT / "samples" / "source"


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Absolute path to the project root."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    """Where the real test songs live."""
    return SAMPLES_DIR


@pytest.fixture(scope="session")
def real_song_paths() -> dict[str, Path]:
    """Map name → path for the 5 reference songs."""
    return {
        "借月":            SAMPLES_DIR / "借月.mp3",
        "离开我的依赖":    SAMPLES_DIR / "离开我的依赖.mp3",
        "跳楼机":          SAMPLES_DIR / "跳楼机.mp3",
        "Brainiac_Maniac": SAMPLES_DIR / "Brainiac_Maniac.mp3",
        "war_drums":       SAMPLES_DIR / "war_drums.m4a",
    }


@pytest.fixture(scope="session")
def vocal_song_path(real_song_paths) -> Path:
    """A canonical vocal song for tests that need just one."""
    return real_song_paths["跳楼机"]


@pytest.fixture(scope="session")
def percussive_song_path(real_song_paths) -> Path:
    """A canonical percussive sample for tests that need just one."""
    return real_song_paths["war_drums"]


# --------------------------------------------------------------------------
# Synthetic-audio fixtures (fast, no disk I/O)
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def synth_sr() -> int:
    """Sample rate used for all synthetic test signals."""
    return 22050


@pytest.fixture(scope="session")
def synth_vocal(synth_sr) -> np.ndarray:
    """A 60-second 'vocal-like' signal: 220 Hz fundamental + harmonics with
    amplitude modulation (mimicking phoneme energy variation).

    Designed so that:
      - mfcc_variance is high (varies with AM)
      - chroma_std is moderate (concentrated near A3)
      - zcr is moderate (sustained tone, no noise)
    """
    sr = synth_sr
    t = np.arange(60 * sr) / sr
    # AM envelope at 4 Hz (vibrato / phoneme rate)
    am = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)
    sig = (
        np.sin(2 * np.pi * 220 * t) * 0.6
        + np.sin(2 * np.pi * 440 * t) * 0.3
        + np.sin(2 * np.pi * 880 * t) * 0.1
    ) * am * 0.6
    return sig.astype(np.float32)


@pytest.fixture(scope="session")
def synth_percussive(synth_sr) -> np.ndarray:
    """A 60-second percussive signal: random transient bursts on top of
    band-limited noise. Simulates a drum loop.

    Designed so that:
      - mfcc_variance is low (timbre static)
      - chroma_std is low (no harmonic motion)
      - onset_rate is moderate (~3-4 onsets/s)
    """
    sr = synth_sr
    rng = np.random.default_rng(42)
    sig = rng.standard_normal(60 * sr).astype(np.float32) * 0.05
    # Add 4 transients per second
    for k in range(4 * 60):
        idx = int(k * sr / 4 + rng.integers(0, sr // 8))
        if idx + 1024 < len(sig):
            burst = rng.standard_normal(1024).astype(np.float32) * 0.6
            sig[idx:idx + 1024] += burst * np.exp(-np.arange(1024) / 200.0)
    return sig


@pytest.fixture(scope="session")
def synth_silent(synth_sr) -> np.ndarray:
    """30 seconds of pure silence — for trivial-input tests."""
    return np.zeros(30 * synth_sr, dtype=np.float32)


# --------------------------------------------------------------------------
# Environment detection
# --------------------------------------------------------------------------

def _has_torch() -> bool:
    try:
        import torch  # noqa
        return True
    except ImportError:
        return False


def _has_mps() -> bool:
    if not _has_torch():
        return False
    import torch
    return torch.backends.mps.is_available() and torch.backends.mps.is_built()


def _has_cuda() -> bool:
    if not _has_torch():
        return False
    import torch
    return torch.cuda.is_available()


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _has_real_audio() -> bool:
    return all((SAMPLES_DIR / name).exists() for name in [
        "借月.mp3", "离开我的依赖.mp3", "跳楼机.mp3",
        "Brainiac_Maniac.mp3", "war_drums.m4a",
    ])


@pytest.fixture(scope="session")
def env_capabilities() -> dict[str, bool]:
    """One-shot env probe used by --doctor and several tests."""
    return {
        "torch": _has_torch(),
        "mps": _has_mps(),
        "cuda": _has_cuda(),
        "ffmpeg": _has_ffmpeg(),
        "real_audio": _has_real_audio(),
    }


# --------------------------------------------------------------------------
# Auto-skip tests whose markers don't match the environment
# --------------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    skip_reasons = {
        "requires_torch": ("torch / [deep] extras not installed", _has_torch()),
        "requires_mps": ("Apple Silicon MPS not available", _has_mps()),
        "requires_cuda": ("NVIDIA CUDA not available", _has_cuda()),
        "requires_ffmpeg": ("ffmpeg not in PATH", _has_ffmpeg()),
        "requires_real_audio": (
            f"real test songs not found in {SAMPLES_DIR}", _has_real_audio()
        ),
    }

    for item in items:
        for marker_name, (reason, ok) in skip_reasons.items():
            if marker_name in item.keywords and not ok:
                item.add_marker(pytest.mark.skip(reason=reason))


# --------------------------------------------------------------------------
# Per-test temp dir for outputs
# --------------------------------------------------------------------------

@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    """Per-test scratch directory."""
    return tmp_path
