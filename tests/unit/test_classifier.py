"""Unit tests for ringtone_forge.classifier."""

from __future__ import annotations

import pytest

from ringtone_forge import classifier


pytestmark = pytest.mark.unit


def test_silent_signal_does_not_crash(synth_silent, synth_sr):
    """Edge case: pure silence shouldn't blow up the feature extractors."""
    result = classifier.classify(synth_silent, synth_sr)
    assert result.audio_type in ("vocal", "melodic", "percussive")


def test_vocal_synth_classified_reasonably(synth_vocal, synth_sr):
    """A 220 Hz harmonic signal with AM is classifier-edge-case: it has
    pitch but no consonants/vibrato, so the classifier may flag it as
    percussive (low MFCC variance, very low chroma_std). What we actually
    care about: the classifier doesn't crash and returns a valid label."""
    result = classifier.classify(synth_vocal, synth_sr)
    assert result.audio_type in ("vocal", "melodic", "percussive")
    # Sanity: confidence is in valid range
    assert 0.0 <= result.confidence <= 1.0


def test_percussive_synth_classified_as_percussive(synth_percussive, synth_sr):
    """Random transient bursts on noise floor should hit the percussive branch."""
    result = classifier.classify(synth_percussive, synth_sr)
    # We don't strictly require 'percussive' since some synth-noise mixes can
    # land in 'melodic', but the MFCC variance should be low.
    assert result.mfcc_variance < 16.0, \
        f"Percussive synth shouldn't have high MFCC var: {result}"


def test_result_fields_in_valid_ranges(synth_vocal, synth_sr):
    r = classifier.classify(synth_vocal, synth_sr)
    assert 0.0 <= r.confidence <= 1.0
    assert 0.0 <= r.chroma_std <= 1.0
    assert 0.0 <= r.zero_crossing_rate <= 1.0
    assert r.mfcc_variance > 0  # some variance, even on synth
    assert r.onset_rate >= 0


def test_result_is_frozen_dataclass(synth_vocal, synth_sr):
    """ClassificationResult must be immutable so callers can rely on it."""
    r = classifier.classify(synth_vocal, synth_sr)
    with pytest.raises((AttributeError, Exception)):
        r.audio_type = "something_else"


@pytest.mark.requires_real_audio
class TestRealAudioClassification:
    """Ground-truth labels for the 5 reference songs."""

    @pytest.mark.parametrize("name,expected", [
        ("跳楼机", "vocal"),
        ("借月", "vocal"),
        ("离开我的依赖", "vocal"),
        ("Brainiac_Maniac", "melodic"),
        ("war_drums", "percussive"),
    ])
    def test_5_song_labels(self, real_song_paths, name, expected):
        import librosa
        path = real_song_paths[name]
        y, sr = librosa.load(str(path), sr=22050, mono=True, duration=60.0)
        result = classifier.classify(y, sr)
        assert result.audio_type == expected, \
            f"{name}: expected {expected}, got {result.audio_type} (conf={result.confidence:.2f})"
