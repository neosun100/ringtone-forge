"""Unit tests for ringtone_forge.analyzer."""

from __future__ import annotations

import numpy as np
import pytest

from ringtone_forge import analyzer


pytestmark = pytest.mark.unit


# --- Synthetic signal with a clear "loud middle" -------------------------

@pytest.fixture(scope="module")
def loud_middle_signal(synth_sr=22050):
    """A 90-second signal where seconds [40, 70] are 3× louder than the rest.
    Any sliding-window analyzer worth its salt should pick start ≈ 40."""
    sr = 22050
    rng = np.random.default_rng(0)
    sig = rng.standard_normal(90 * sr).astype(np.float32) * 0.05
    sig[40 * sr: 70 * sr] *= 6.0
    return sig, sr


# --- T1 -------------------------------------------------------------------

class TestLoudnessAlgo:
    def test_picks_loud_section(self, loud_middle_signal):
        sig, sr = loud_middle_signal
        candidates = analyzer.analyze_loudness(sig, sr, top_k=3)
        assert len(candidates) == 3
        # The top pick should be inside [38, 45] — start of the loud band
        # (with some tolerance for edge effects).
        top = candidates[0].start_seconds
        assert 35 <= top <= 45, f"T1 loudness picked {top}s, expected ~40s"

    def test_short_audio_returns_single_candidate(self):
        sig = np.zeros(20 * 22050, dtype=np.float32)
        cands = analyzer.analyze_loudness(sig, 22050)
        assert len(cands) == 1
        assert cands[0].start_seconds == 0.0


# --- T2 -------------------------------------------------------------------

class TestFeaturesAlgo:
    def test_picks_loud_section(self, loud_middle_signal):
        sig, sr = loud_middle_signal
        candidates = analyzer.analyze_features(sig, sr, audio_type="vocal", top_k=3)
        assert len(candidates) == 3
        top = candidates[0].start_seconds
        assert 35 <= top <= 50, f"T2 features picked {top}s, expected ~40s"

    @pytest.mark.parametrize("audio_type", ["vocal", "melodic", "percussive"])
    def test_returns_candidates_for_each_type(self, loud_middle_signal, audio_type):
        sig, sr = loud_middle_signal
        candidates = analyzer.analyze_features(sig, sr, audio_type=audio_type, top_k=5)
        assert len(candidates) == 5
        # Scores should be in [0, 1] and descending
        scores = [c.score for c in candidates]
        assert all(0 <= s <= 1 for s in scores)
        assert scores == sorted(scores, reverse=True)


# --- T3 -------------------------------------------------------------------

class TestStructuralAlgo:
    def test_does_not_crash_on_random_audio(self, loud_middle_signal):
        """SSM-based; should at least produce candidates without erroring."""
        sig, sr = loud_middle_signal
        candidates = analyzer.analyze_structural(sig, sr, top_k=3)
        assert len(candidates) >= 1
        for c in candidates:
            assert 0 <= c.start_seconds <= 60  # window starts must fit


# --- analyze() dispatcher ------------------------------------------------

class TestAnalyzeDispatcher:
    @pytest.mark.parametrize("algo", ["loudness", "features", "structural"])
    def test_dispatch(self, loud_middle_signal, algo):
        sig, sr = loud_middle_signal
        cands = analyzer.analyze(sig, sr, algorithm=algo, top_k=3)
        assert len(cands) >= 1

    def test_unknown_algo_raises(self, loud_middle_signal):
        sig, sr = loud_middle_signal
        with pytest.raises(ValueError):
            analyzer.analyze(sig, sr, algorithm="bogus")
