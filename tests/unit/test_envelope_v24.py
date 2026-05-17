"""Unit tests for v2.4 envelope parameter overrides + duration scaling."""

from __future__ import annotations

import pytest

from ringtone_forge import envelope


pytestmark = pytest.mark.unit


class TestEnvelopeOverrides:
    """get_preset() now accepts override kwargs."""

    def test_no_overrides_matches_default(self):
        a = envelope.get_preset("vocal")
        b = envelope.get_preset("vocal")
        assert a == b

    def test_override_rise(self):
        p = envelope.get_preset("vocal", rise=10.0)
        assert p.rise_seconds == 10.0
        # other fields untouched
        assert p.sustain_seconds == 22.0
        assert p.drop_seconds == 3.0
        assert p.start_amp == 0.50

    def test_override_start_amp(self):
        p = envelope.get_preset("vocal", start_amp=0.25)
        assert p.start_amp == 0.25

    def test_override_all_three_durations(self):
        p = envelope.get_preset("vocal", rise=8, sustain=19, drop=3)
        assert (p.rise_seconds, p.sustain_seconds, p.drop_seconds) == (8.0, 19.0, 3.0)

    def test_invalid_start_amp_raises(self):
        with pytest.raises(ValueError):
            envelope.get_preset("vocal", start_amp=1.5)
        with pytest.raises(ValueError):
            envelope.get_preset("vocal", start_amp=0)

    def test_negative_duration_raises(self):
        with pytest.raises(ValueError):
            envelope.get_preset("vocal", rise=-1.0)


class TestDurationScaling:
    """When duration != preset.total_seconds, rise/sustain/drop scale proportionally."""

    def test_default_duration_no_scaling(self):
        p = envelope.get_preset("vocal", duration=30.0)
        assert p.rise_seconds == 5.0
        assert p.sustain_seconds == 22.0
        assert p.drop_seconds == 3.0

    def test_scaled_to_15_seconds(self):
        """30s → 15s should halve all durations."""
        p = envelope.get_preset("vocal", duration=15.0)
        assert p.rise_seconds == pytest.approx(2.5)
        assert p.sustain_seconds == pytest.approx(11.0)
        assert p.drop_seconds == pytest.approx(1.5)

    def test_scaled_to_60_seconds(self):
        """30s → 60s should double all durations."""
        p = envelope.get_preset("vocal", duration=60.0)
        assert p.rise_seconds == pytest.approx(10.0)
        assert p.sustain_seconds == pytest.approx(44.0)
        assert p.drop_seconds == pytest.approx(6.0)

    def test_explicit_override_beats_scaling(self):
        """Explicit rise= overrides the scaled value."""
        p = envelope.get_preset("vocal", duration=15.0, rise=3.0)
        assert p.rise_seconds == 3.0
        # sustain and drop are still scaled
        assert p.sustain_seconds == pytest.approx(11.0)


class TestResolveEnvelopeParams:
    """The single resolution entry point used by the CLI."""

    def test_audio_type_drives_preset(self):
        p = envelope.resolve_envelope_params(audio_type="vocal")
        assert p.name == "vocal"
        p = envelope.resolve_envelope_params(audio_type="percussive")
        assert p.name == "percussive"

    def test_user_preset_overrides_audio_type(self):
        p = envelope.resolve_envelope_params(audio_type="vocal", user_preset="percussive")
        assert p.name == "percussive"

    def test_user_overrides_apply(self):
        p = envelope.resolve_envelope_params(
            audio_type="vocal",
            user_rise=8.0,
            user_start_amp=0.3,
        )
        assert p.rise_seconds == 8.0
        assert p.start_amp == 0.3

    def test_user_duration_scales_other_fields(self):
        p = envelope.resolve_envelope_params(audio_type="vocal", user_duration=15.0)
        assert p.rise_seconds == pytest.approx(2.5)
        assert p.total_seconds == pytest.approx(15.0)
