"""Unit tests for ringtone_forge.llm_tuner — uses the mock backend so no API key needed."""

from __future__ import annotations

import pytest

from ringtone_forge import llm_tuner


pytestmark = pytest.mark.unit


# --- detect_available_backends ---

def test_detect_returns_at_least_mock():
    """The mock backend is always available."""
    available = llm_tuner.detect_available_backends()
    assert "mock" in available


# --- TuningResult dataclass ---

def test_tuning_result_to_envelope_kwargs_filters_nones():
    """to_envelope_kwargs() should only include non-None fields."""
    r = llm_tuner.TuningResult(rise=5.0, sustain=None, drop=3.0, start_amp=0.4, duration=None)
    kwargs = r.to_envelope_kwargs()
    assert kwargs == {
        "user_rise": 5.0,
        "user_drop": 3.0,
        "user_start_amp": 0.4,
    }


def test_tuning_result_empty_when_all_none():
    r = llm_tuner.TuningResult()
    assert r.to_envelope_kwargs() == {}


# --- mock backend tuning ---

class TestMockTuneFromPreference:
    def test_lighter_start_keyword(self):
        """The mock recognises '开头/lighter/slow' keywords and adjusts."""
        result = llm_tuner.tune_from_preference("vocal", "开头再轻一点", backend="mock")
        assert result.backend == "mock"
        assert result.rise == 10.0
        assert result.start_amp == 0.30

    def test_punchier_keyword(self):
        result = llm_tuner.tune_from_preference("vocal", "更带感一点", backend="mock")
        assert result.backend == "mock"
        assert result.rise == 3.0
        assert result.sustain == 24.0
        assert result.start_amp == 0.6

    def test_neutral_request_returns_no_changes(self):
        """A request without recognised keywords returns all-Nones."""
        result = llm_tuner.tune_from_preference("vocal", "做个铃声就好", backend="mock")
        assert result.backend == "mock"
        assert result.rise is None
        assert result.start_amp is None

    def test_explanation_is_present(self):
        result = llm_tuner.tune_from_preference("vocal", "开头再轻一点", backend="mock")
        assert result.explanation
        assert "[mock]" in result.explanation

    def test_classification_features_are_optional(self):
        result = llm_tuner.tune_from_preference(
            "vocal", "开头轻一点",
            classification_features={"mfcc_variance": 14.5, "chroma_std": 0.28},
            backend="mock",
        )
        assert result.backend == "mock"
        assert result.rise == 10.0


# --- mock backend diagnose ---

class TestMockDiagnose:
    def test_diagnose_returns_tuning_result(self):
        result = llm_tuner.diagnose_verify_failure(
            failed_checks=[{"name": "RMS at t=0s < -25 dB", "actual": "-18 dB"}],
            current_params={"rise": 5.0, "start_amp": 0.5},
            backend="mock",
        )
        assert result.backend == "mock"
        assert result.explanation


# --- backend selection ---

class TestBackendResolution:
    def test_explicit_mock(self):
        backend = llm_tuner._resolve_backend("mock")
        assert backend == "mock"

    def test_auto_selects_some_backend(self):
        backend = llm_tuner._resolve_backend("auto")
        assert backend in ("anthropic", "openai", "ollama", "mock")


# --- response parsing ---

class TestParseResponse:
    def test_plain_json(self):
        raw = '{"rise": 10, "explanation": "ok"}'
        data = llm_tuner._parse_response(raw)
        assert data["rise"] == 10

    def test_fenced_json(self):
        raw = 'Here is my response:\n```json\n{"rise": 5}\n```\nThanks!'
        data = llm_tuner._parse_response(raw)
        assert data["rise"] == 5

    def test_json_with_surrounding_prose(self):
        raw = 'I think we should set: {"rise": 8, "drop": 4}\nThat should work.'
        data = llm_tuner._parse_response(raw)
        assert data["rise"] == 8
        assert data["drop"] == 4

    def test_unparseable_raises(self):
        with pytest.raises(ValueError):
            llm_tuner._parse_response("just plain text, no JSON anywhere")
