"""Regression tests — pin known-good selections on the 5 reference songs.

These tests guard against silent regressions when dependencies upgrade
or when we tweak the analyzer. If a song's pick shifts more than the
allowed tolerance, the test fails — at which point a human listens to
the new pick and either accepts the change (update the expected value)
or finds the bug.
"""

from __future__ import annotations

import pytest

from ringtone_forge import classifier
from ringtone_forge import stems_analyzer


pytestmark = [
    pytest.mark.regression,
    pytest.mark.requires_torch,
    pytest.mark.requires_real_audio,
    pytest.mark.slow,
]


# --------------------------------------------------------------------------
# Pinned classification labels (v2.2 baseline)
# --------------------------------------------------------------------------

EXPECTED_CLASSIFICATIONS = {
    "借月":            ("vocal",      0.80),  # name → (audio_type, min_confidence)
    "离开我的依赖":    ("vocal",      0.80),
    "跳楼机":          ("vocal",      0.80),
    "Brainiac_Maniac": ("melodic",    0.50),
    "war_drums":       ("percussive", 0.60),
}


@pytest.mark.parametrize("name,expected", EXPECTED_CLASSIFICATIONS.items())
def test_classification_label_pinned(real_song_paths, name, expected):
    expected_type, min_conf = expected
    import librosa
    y, sr = librosa.load(str(real_song_paths[name]), sr=22050, mono=True, duration=60.0)
    result = classifier.classify(y, sr)
    assert result.audio_type == expected_type, \
        f"{name}: expected {expected_type}, got {result.audio_type}"
    assert result.confidence >= min_conf, \
        f"{name}: confidence {result.confidence:.2f} < {min_conf}"


# --------------------------------------------------------------------------
# Pinned chorus picks (v2.2 stems analyzer)
# --------------------------------------------------------------------------
#
# Tolerance: ±2 seconds. Picks shouldn't drift more than that from the
# v2.2 baseline. If they do, run --analyze on the failing song and decide
# whether to update the pinned value.

PINNED_PICKS_V22 = {
    # name → (expected_start_seconds, tolerance_seconds, primary_stem)
    "借月":            (137.5, 2.0, "vocals"),
    "离开我的依赖":    (187.0, 2.0, "vocals"),
    "跳楼机":          (144.5, 2.0, "vocals"),
    "Brainiac_Maniac": ( 32.0, 5.0, "other"),  # instrumental, more variance allowed
    "war_drums":       (  1.0, 2.0, None),     # short loop; stem name varies
}


@pytest.mark.parametrize("name,expected", PINNED_PICKS_V22.items())
def test_chorus_pick_pinned(real_song_paths, name, expected):
    expected_start, tol, expected_stem = expected
    result = stems_analyzer.find_chorus_window_stems(
        str(real_song_paths[name]),
        device="auto",
        top_k=3,
    )
    delta = abs(result.chorus_start_seconds - expected_start)
    assert delta <= tol, (
        f"{name}: chorus start regressed — expected {expected_start}±{tol}s, "
        f"got {result.chorus_start_seconds:.1f}s (Δ={delta:.1f}s). "
        f"primary stem: {result.primary_stem}, confidence {result.confidence:.2f}. "
        f"Update PINNED_PICKS_V22 if the new pick is intentionally better."
    )
    if expected_stem is not None:
        assert result.primary_stem == expected_stem, (
            f"{name}: primary stem changed — expected {expected_stem}, "
            f"got {result.primary_stem}"
        )
