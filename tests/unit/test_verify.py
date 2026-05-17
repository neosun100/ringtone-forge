"""Unit tests for ringtone_forge.verify.

The verify module shells out to ffmpeg/ffprobe, so we mark its tests with
requires_ffmpeg. Logic-only assertions (helper functions, expected dB
calculations) run without ffmpeg.
"""

from __future__ import annotations

import math

import pytest

from ringtone_forge import verify


# Pure-math helper tests — no ffmpeg ----------------------------------

class TestExpectedStartDb:
    @pytest.mark.unit
    def test_full_amplitude_is_zero_db(self):
        """v=1.0 → 0 dB."""
        assert verify._expected_start_db(1.0) == pytest.approx(0.0, abs=1e-6)

    @pytest.mark.unit
    @pytest.mark.parametrize("amp,expected_db", [
        (0.5, -6.02),
        (0.2, -13.98),
        (0.3, -10.46),
        (0.1, -20.0),
    ])
    def test_amp_to_db_table(self, amp, expected_db):
        result = verify._expected_start_db(amp)
        assert result == pytest.approx(expected_db, abs=0.05)


# CheckResult dataclass --------------------------------------------------

class TestCheckResultDataclass:
    @pytest.mark.unit
    def test_check_result_fields(self):
        c = verify.CheckResult(name="x", passed=True, actual="ok")
        assert c.name == "x" and c.passed and c.actual == "ok"
        assert c.detail == ""


# VerifyReport aggregation -----------------------------------------------

class TestVerifyReportAggregation:
    @pytest.mark.unit
    def test_all_passed_property(self):
        r = verify.VerifyReport(file="x")
        r.checks.append(verify.CheckResult("a", True, "ok"))
        r.checks.append(verify.CheckResult("b", True, "ok"))
        assert r.all_passed
        assert r.failures == 0

    @pytest.mark.unit
    def test_failures_count(self):
        r = verify.VerifyReport(file="x")
        r.checks.append(verify.CheckResult("a", True, "ok"))
        r.checks.append(verify.CheckResult("b", False, "bad"))
        r.checks.append(verify.CheckResult("c", False, "bad"))
        assert not r.all_passed
        assert r.failures == 2


# End-to-end via ffmpeg --------------------------------------------------

@pytest.mark.requires_ffmpeg
@pytest.mark.requires_real_audio
@pytest.mark.integration
class TestVerifyOnRealRingtone:
    def test_verify_runs_against_v22_sample(self, project_root):
        """We have a known-good v2.2 ringtone in samples/final-v22/."""
        sample = project_root / "samples" / "final-v22" / "跳楼机_v22.m4a"
        if not sample.exists():
            pytest.skip(f"sample {sample} missing")

        report = verify.verify(
            sample,
            preset_start_amp=0.50,
            preset_rise_seconds=5.0,
            preset_sustain_seconds=22.0,
            source_lufs=None,  # skip source-integrity check
        )
        # Should produce checks
        assert len(report.checks) >= 5
        # Duration check should be a pass (ringtone is 30s)
        duration_checks = [c for c in report.checks if "duration" in c.name.lower()]
        assert len(duration_checks) == 1
        assert duration_checks[0].passed
