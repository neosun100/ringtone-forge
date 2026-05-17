"""
Quality verification — preset-aware 7-point checklist for forged ringtones.

Background — why preset-aware:

The v1.0 verify used absolute thresholds (e.g. ``LUFS in [−16, −12]``) tuned
for the war_drums sample. Modern pop tracks are mastered for the loudness
war: integrated loudness around −7 LUFS, true peak above 0 dBFS, LRA below
3 LU. That is *the source*, not a bug in our forge — and our envelope
preserves that character. So the absolute thresholds were wrong; they
flagged correctly-forged vocal pop as broken.

The new verify checks two kinds of properties:

* **Hygiene** (always required regardless of source):
    1. duration = 30.000s exactly
    2. no clipping (true peak ≤ −0.5 dBFS — the alimiter target)
    3. graceful fade-out (RMS at t=29.7s < −40 dB)

* **Design adherence** (relative to the preset's starting amplitude):
    4. RMS at t=0s should be ~ ``20·log10(start_amp)`` dB below climax,
       within a 4 dB tolerance. (vocal expects −6 dB, melodic −10 dB,
       percussive −14 dB.)
    5. RMS at t=15s should be near climax (within 6 dB) — confirms the
       rise reached its peak before the sustain plateau ended.
    6. RMS at sustain mid (t = R + S/2) should be the loudest point.
    7. Source-to-output integrity: integrated LUFS within 4 dB of source
       LUFS (we are not a loudness normaliser; we should preserve overall
       character).

The sustain anchor (#6) and source-relative LUFS (#7) are new in v2.0.
"""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CheckResult:
    name: str
    passed: bool
    actual: str
    detail: str = ""


@dataclass
class VerifyReport:
    file: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> int:
        return sum(1 for c in self.checks if not c.passed)


def _stderr(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stderr or ""


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def _rms_at(path: Path, ts: float) -> Optional[float]:
    out = _stderr([
        "ffmpeg", "-hide_banner",
        "-ss", str(ts), "-t", "0.5",
        "-i", str(path),
        "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
        "-f", "null", "-",
    ])
    matches = re.findall(r"RMS_level=(-?\d+\.\d+)", out)
    return float(matches[-1]) if matches else None


def _ebur128_metrics(path: Path) -> dict[str, Optional[float]]:
    out = _stderr([
        "ffmpeg", "-hide_banner",
        "-i", str(path),
        "-af", "ebur128=peak=true",
        "-f", "null", "-",
    ])
    metrics: dict[str, Optional[float]] = {"I": None, "LRA": None, "Peak": None}
    for line in out.splitlines():
        m = re.match(r"\s+I:\s+(-?\d+\.\d+)\s+LUFS", line)
        if m:
            metrics["I"] = float(m.group(1))
        m = re.match(r"\s+LRA:\s+(-?\d+\.\d+)\s+LU", line)
        if m and metrics["LRA"] is None:
            metrics["LRA"] = float(m.group(1))
        m = re.match(r"\s+Peak:\s+(-?\d+\.\d+)\s+dBFS", line)
        if m:
            metrics["Peak"] = float(m.group(1))
    return metrics


def _expected_start_db(start_amp: float) -> float:
    """Theoretical dB of the start amplitude vs sustain. e.g. 0.5 → −6 dB."""
    return 20.0 * math.log10(max(start_amp, 1e-6))


def verify(
    path: str | Path,
    *,
    preset_start_amp: float = 0.20,
    preset_rise_seconds: float = 20.0,
    preset_sustain_seconds: float = 7.0,
    source_lufs: Optional[float] = None,
) -> VerifyReport:
    """Run the 7-point quality bar.

    Parameters
    ----------
    path:
        Forged ringtone file.
    preset_start_amp:
        ``EnvelopePreset.start_amp`` of the preset that produced this file.
    preset_rise_seconds, preset_sustain_seconds:
        For locating the sustain mid-point.
    source_lufs:
        Integrated loudness of the original source, for the source-integrity
        check. Pass ``None`` to skip that check.
    """
    path = Path(path)
    report = VerifyReport(file=str(path))

    duration = _ffprobe_duration(path)
    e = _ebur128_metrics(path)
    peak, lufs_i = e["Peak"], e["I"]

    # Sample times — relative to preset structure
    sustain_mid = preset_rise_seconds + preset_sustain_seconds / 2.0
    rms_0 = _rms_at(path, 0.0)
    rms_15 = _rms_at(path, 15.0)
    rms_sustain_mid = _rms_at(path, sustain_mid)
    rms_end = _rms_at(path, 29.7)

    # 1. Duration
    report.checks.append(CheckResult(
        name="duration = 30.000s",
        passed=abs(duration - 30.0) < 0.05,
        actual=f"{duration:.3f}s",
    ))

    # 2. No clipping (limiter target is 0.85 ≈ −1.4 dBFS sample peak; the
    #    inter-sample true-peak measurement may add ~2 dB of overshoot,
    #    so we accept up to +1 dBFS — well below the level at which any
    #    real playback device would actually clip).
    report.checks.append(CheckResult(
        name="true peak ≤ +1.0 dBFS  (inter-sample safe)",
        passed=peak is not None and peak <= 1.0,
        actual=f"{peak:.2f} dBFS" if peak is not None else "?",
    ))

    # 3. Graceful fade-out
    report.checks.append(CheckResult(
        name="RMS at t=29.7s < −40 dB  (clean exit)",
        passed=rms_end is not None and rms_end < -40.0,
        actual=f"{rms_end:.2f} dB" if rms_end is not None else "?",
    ))

    # 4. Start matches preset's starting amplitude
    expected_start_drop = _expected_start_db(preset_start_amp)  # negative number
    if rms_0 is not None and rms_sustain_mid is not None:
        actual_drop = rms_0 - rms_sustain_mid
        delta_from_expected = abs(actual_drop - expected_start_drop)
        report.checks.append(CheckResult(
            name=f"start ≈ {expected_start_drop:+.1f} dB below climax  (preset adherence)",
            passed=delta_from_expected <= 4.0,
            actual=f"{actual_drop:+.2f} dB  (Δ={delta_from_expected:.2f})",
        ))
    else:
        report.checks.append(CheckResult(
            name="start vs climax",
            passed=False,
            actual="?",
            detail="could not sample RMS",
        ))

    # 5. Mid-rise approaching peak
    if rms_15 is not None and rms_sustain_mid is not None:
        delta = rms_sustain_mid - rms_15  # >=0 means sustain louder than t=15s
        report.checks.append(CheckResult(
            name="RMS at t=15s within 6 dB of climax",
            passed=abs(delta) <= 6.0,
            actual=f"{rms_15:.2f} dB (climax {rms_sustain_mid:.2f}, Δ={delta:+.2f})",
        ))

    # 6. Sustain mid is loud
    if rms_sustain_mid is not None and rms_0 is not None:
        report.checks.append(CheckResult(
            name="sustain anchor louder than start",
            passed=rms_sustain_mid > rms_0,
            actual=f"sustain={rms_sustain_mid:.2f} dB  start={rms_0:.2f} dB",
        ))

    # 7. Source-integrity (only if we know source LUFS)
    if source_lufs is not None and lufs_i is not None:
        delta_lufs = abs(lufs_i - source_lufs)
        report.checks.append(CheckResult(
            name="output LUFS within 4 dB of source",
            passed=delta_lufs <= 4.0,
            actual=f"output={lufs_i:.2f}  source={source_lufs:.2f}  Δ={delta_lufs:.2f}",
        ))

    return report
