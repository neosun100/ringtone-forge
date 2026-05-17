"""Unit tests for ringtone_forge.stems_analyzer.

Heavy demucs inference is gated behind requires_torch + slow markers so
this file's pure-math tests still pass without [deep] extras.
"""

from __future__ import annotations

import pytest

from ringtone_forge import stems_analyzer


pytestmark = pytest.mark.unit


# --- chorus_aware_trim_start -----------------------------------------

class TestChorusAwareTrimStart:
    """The alignment math is pure Python — must work regardless of torch."""

    def test_chorus_in_middle_aligns_to_sustain_mid(self):
        """A 30s chorus at [60, 90]; vocal preset rise=5, sustain=22, sustain_mid=16.
        chorus_mid = 75, expected trim_start = 75 - 16 = 59."""
        ts = stems_analyzer.chorus_aware_trim_start(
            chorus_start=60.0, chorus_end=90.0,
            preset_rise_seconds=5.0, preset_sustain_seconds=22.0,
            source_duration=240.0,
        )
        assert abs(ts - 59.0) < 1e-9

    def test_chorus_near_start_clamped_to_zero(self):
        """If chorus_mid < sustain_mid, can't go negative — clamp."""
        ts = stems_analyzer.chorus_aware_trim_start(
            chorus_start=2.0, chorus_end=8.0,
            preset_rise_seconds=20.0, preset_sustain_seconds=7.0,
            source_duration=60.0,
        )
        assert ts == 0.0

    def test_chorus_near_end_clamped(self):
        """If aligning would run past EOF, clamp to (duration - 30)."""
        ts = stems_analyzer.chorus_aware_trim_start(
            chorus_start=240.0, chorus_end=270.0,
            preset_rise_seconds=5.0, preset_sustain_seconds=22.0,
            source_duration=276.0,
        )
        # chorus_mid=255, sustain_mid=16 → naive = 239; but 239+30=269 < 276 OK
        # so should get 239
        assert abs(ts - 239.0) < 1e-9

    def test_clamped_at_eof_when_alignment_would_overshoot(self):
        """A chorus at the very last second should clamp to (duration - 30)."""
        ts = stems_analyzer.chorus_aware_trim_start(
            chorus_start=270.0, chorus_end=276.0,
            preset_rise_seconds=20.0, preset_sustain_seconds=7.0,
            source_duration=276.0,
        )
        # chorus_mid=273, sustain_mid_in_ringtone = 23.5; naive trim_start=249.5
        # 249.5+30=279.5 > 276 → clamp to 246
        assert ts == pytest.approx(276.0 - 30.0)

    def test_different_presets_produce_different_alignments(self):
        """Same chorus, different presets → different trim_starts.
        
        vocal preset: sustain_mid in ringtone = 5 + 22/2 = 16s
        percussive preset: sustain_mid in ringtone = 20 + 7/2 = 23.5s
        
        For chorus_mid=75:
          vocal:      trim_start = 75 - 16 = 59
          percussive: trim_start = 75 - 23.5 = 51.5  (earlier in source)
        
        So percussive trim_start < vocal trim_start (percussive starts
        earlier in the source to give more rise-time before the chorus).
        """
        chorus = (60.0, 90.0)
        ts_vocal = stems_analyzer.chorus_aware_trim_start(
            *chorus, preset_rise_seconds=5.0, preset_sustain_seconds=22.0,
            source_duration=240.0,
        )
        ts_perc = stems_analyzer.chorus_aware_trim_start(
            *chorus, preset_rise_seconds=20.0, preset_sustain_seconds=7.0,
            source_duration=240.0,
        )
        assert ts_perc < ts_vocal  # percussive starts earlier (more rise)
        assert ts_vocal == pytest.approx(75.0 - 16.0)
        assert ts_perc == pytest.approx(75.0 - 23.5)


# --- device selection ------------------------------------------------

@pytest.mark.requires_torch
class TestDeviceSelection:
    def test_auto_picks_available_backend(self):
        device = stems_analyzer._select_device("auto")
        assert device in ("mps", "cuda", "cpu")

    def test_cpu_is_always_available(self):
        device = stems_analyzer._select_device("cpu")
        assert device == "cpu"

    def test_unknown_device_falls_back(self):
        """Requesting a bogus device should fall back to auto."""
        device = stems_analyzer._select_device("nonexistent")
        assert device in ("mps", "cuda", "cpu")


# --- continuity score (pure numpy) -----------------------------------

class TestContinuityScore:
    def test_constant_signal_is_fully_above_threshold(self):
        import numpy as np
        # A constant signal at 1.0 — every frame is at peak
        rms = np.ones(100, dtype=np.float32)
        score = stems_analyzer._continuity_score(rms, threshold_pct=0.30)
        assert score == 1.0

    def test_silent_signal_is_zero(self):
        import numpy as np
        rms = np.zeros(100, dtype=np.float32)
        score = stems_analyzer._continuity_score(rms)
        assert score == 0.0

    def test_single_spike_low_continuity(self):
        """One loud spike, rest near silent → low continuity."""
        import numpy as np
        rms = np.zeros(100, dtype=np.float32)
        rms[50] = 1.0
        score = stems_analyzer._continuity_score(rms, threshold_pct=0.30)
        # Only 1/100 frames above 30% → score = 0.01
        assert score == pytest.approx(0.01)


# --- end-to-end (slow, requires torch) -------------------------------

@pytest.mark.requires_torch
@pytest.mark.requires_real_audio
@pytest.mark.slow
class TestStemsAnalyzerEndToEnd:
    def test_runs_on_real_song(self, percussive_song_path):
        """Smoke test: stems analyzer runs on war_drums without crashing."""
        result = stems_analyzer.find_chorus_window_stems(
            str(percussive_song_path),
            device="auto",
            top_k=3,
        )
        assert 0.0 <= result.chorus_start_seconds < result.chorus_end_seconds
        assert result.chorus_end_seconds - result.chorus_start_seconds == pytest.approx(30.0)
        assert result.primary_stem in ("vocals", "other")
        assert result.device_used in ("mps", "cuda", "cpu")
        assert result.seconds_to_separate > 0
