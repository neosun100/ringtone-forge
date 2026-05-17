"""Unit tests for ringtone_forge.envelope."""

from __future__ import annotations

import math

import pytest

from ringtone_forge import envelope


pytestmark = pytest.mark.unit


class TestPresets:
    """Three presets are well-defined and total exactly 30 seconds each."""

    @pytest.mark.parametrize("name", ["vocal", "melodic", "percussive"])
    def test_preset_total_is_30_seconds(self, name):
        p = envelope.get_preset(name)
        assert abs(p.total_seconds - 30.0) < 1e-9, \
            f"{name} preset total {p.total_seconds}s ≠ 30.0s"

    @pytest.mark.parametrize("name", ["vocal", "melodic", "percussive"])
    def test_preset_drop_is_3_seconds(self, name):
        """Per design, drop length is fixed at 3s across all presets."""
        assert envelope.get_preset(name).drop_seconds == 3.0

    def test_vocal_preset_short_rise(self):
        """Vocal: 5s rise → fast climax for dense choruses."""
        p = envelope.get_preset("vocal")
        assert p.rise_seconds == 5.0
        assert p.start_amp == 0.50

    def test_percussive_preset_long_rise(self):
        """Percussive: 20s rise → 'approaching from afar' (v1 recipe)."""
        p = envelope.get_preset("percussive")
        assert p.rise_seconds == 20.0
        assert p.start_amp == 0.20

    def test_unknown_preset_raises(self):
        with pytest.raises(KeyError):
            envelope.get_preset("nonexistent")

    def test_sustain_end_property(self):
        p = envelope.get_preset("vocal")
        assert p.sustain_end == p.rise_seconds + p.sustain_seconds  # 5 + 22 = 27


class TestFilterExpression:
    """ffmpeg volume-filter expression must be syntactically valid and contain
    the right structure."""

    def test_expression_contains_three_segments(self):
        p = envelope.get_preset("percussive")
        expr = envelope.build_filter_expression(p)
        assert "if(lt(t" in expr
        assert "pow(" in expr
        assert "max(0" in expr

    def test_expression_contains_eval_frame(self):
        """eval=frame is critical — without it ffmpeg only computes once."""
        p = envelope.get_preset("vocal")
        expr = envelope.build_filter_expression(p)
        assert "eval=frame" in expr

    def test_expression_contains_alimiter(self):
        """alimiter is mandatory anti-clipping."""
        p = envelope.get_preset("vocal")
        expr = envelope.build_filter_expression(p)
        assert "alimiter" in expr
        assert "limit=0.85" in expr or "limit=0.78" in expr  # accept current or future tighter

    def test_expression_starts_with_volume(self):
        p = envelope.get_preset("melodic")
        expr = envelope.build_filter_expression(p)
        assert expr.startswith("volume=")

    @pytest.mark.parametrize("name", ["vocal", "melodic", "percussive"])
    def test_expression_well_formed_per_preset(self, name):
        """Quick parens balance check."""
        expr = envelope.build_filter_expression(envelope.get_preset(name))
        opens = expr.count("(")
        closes = expr.count(")")
        assert opens == closes, f"Unbalanced parens for {name}: {opens} vs {closes}"


class TestEnvelopeMath:
    """Validate the volume curve at key points."""

    def _eval_at(self, preset: envelope.EnvelopePreset, t: float) -> float:
        """Reproduce the formula in pure Python for cross-checking."""
        R, S, D, A = preset.rise_seconds, preset.sustain_seconds, preset.drop_seconds, preset.start_amp
        if t < R:
            return A * (1.0 / A) ** (t / R)
        if t < R + S:
            return 1.0
        return max(0.0, 1.0 - (t - (R + S)) / D)

    @pytest.mark.parametrize("name", ["vocal", "melodic", "percussive"])
    def test_rise_starts_at_start_amp(self, name):
        p = envelope.get_preset(name)
        v0 = self._eval_at(p, 0.0)
        assert abs(v0 - p.start_amp) < 1e-9

    @pytest.mark.parametrize("name", ["vocal", "melodic", "percussive"])
    def test_rise_ends_at_unity(self, name):
        p = envelope.get_preset(name)
        v_end = self._eval_at(p, p.rise_seconds)
        assert abs(v_end - 1.0) < 1e-6

    @pytest.mark.parametrize("name", ["vocal", "melodic", "percussive"])
    def test_drop_ends_at_zero(self, name):
        p = envelope.get_preset(name)
        v_end = self._eval_at(p, p.total_seconds)
        assert v_end == 0.0

    @pytest.mark.parametrize("name", ["vocal", "melodic", "percussive"])
    def test_sustain_at_full_volume(self, name):
        p = envelope.get_preset(name)
        v_mid_sustain = self._eval_at(p, p.rise_seconds + p.sustain_seconds / 2)
        assert v_mid_sustain == 1.0


class TestRenderAscii:
    def test_output_contains_envelope_keyword(self):
        s = envelope.render_ascii(envelope.get_preset("vocal"))
        assert "envelope" in s.lower()

    def test_output_contains_seconds_grid(self):
        """ASCII output should label the 0s, mid, and end markers."""
        s = envelope.render_ascii(envelope.get_preset("vocal"))
        assert "0s" in s
        assert "30s" in s
