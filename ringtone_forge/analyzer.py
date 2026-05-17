"""
Window analyzer — find the best 30-second segment of a song.

Three algorithms, in increasing sophistication:

T1. Loudness-max (``loudness``)
    Slide a 30s window across the EBU-R128 momentary-loudness trace and pick
    the window with the highest mean energy. Pure ffmpeg upstream — no
    librosa needed if this tier alone is used. Best for content where the
    climax is unambiguously the loudest section (most pop/rock).

T2. Multi-feature scoring (``features``)  ← default
    Combine four normalised features into one score, then slide the window:
      - RMS energy      (loudness)
      - spectral contrast  (timbral richness — bass + mid + treble all alive)
      - onset density    (rhythmic intensity)
      - spectral centroid (timbral brightness, often higher in choruses)
    Weights are *audio-type-aware* — vocals weight RMS heavily because
    choruses are louder and richer; percussive material weights RMS even
    more because nothing else varies; melodic instrumentals balance more
    evenly.

T3. Structural chorus (``structural``)
    Build a self-similarity matrix of chroma features and detect the
    segment that repeats most often. The chorus is, definitionally, the
    section the song returns to; we ride that statistical fact rather than
    proxying for it.

All tiers return a list of Candidate objects with start time and per-feature
scores so the analyse-only mode can show the user a transparent ranking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np


Algorithm = Literal["loudness", "features", "structural"]


@dataclass
class Candidate:
    """A 30-second window candidate.

    Attributes
    ----------
    start_seconds:
        Start of the window, in seconds from the beginning of the source.
    score:
        Aggregate score in [0, 1]. Higher = better. Normalised within a
        single analysis run; cannot be compared across runs.
    features:
        Per-feature scores that contributed to ``score`` (debug detail).
    """

    start_seconds: float
    score: float
    features: dict = field(default_factory=dict)

    def end_seconds(self, duration: float = 30.0) -> float:
        return self.start_seconds + duration


# ---------------------------------------------------------------------------
# Feature weights — chosen by tuning on a small but diverse test set.
# vocal     : RMS dominates (chorus is louder), centroid catches harmony layering.
# melodic   : balanced — instrumentals can climax via texture or rhythm too.
# percussive: RMS dominates almost completely; nothing else varies enough to matter.
# ---------------------------------------------------------------------------

_WEIGHTS: dict[str, dict[str, float]] = {
    "vocal":      {"rms": 0.45, "contrast": 0.20, "onset": 0.10, "centroid": 0.25},
    "melodic":    {"rms": 0.30, "contrast": 0.30, "onset": 0.25, "centroid": 0.15},
    "percussive": {"rms": 0.70, "contrast": 0.10, "onset": 0.10, "centroid": 0.10},
}


def _normalise(x: np.ndarray) -> np.ndarray:
    """Min-max scale a 1-D array to [0, 1]; constant input maps to 0.5."""
    lo, hi = float(np.min(x)), float(np.max(x))
    if hi - lo < 1e-9:
        return np.full_like(x, 0.5, dtype=float)
    return (x - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# T1 — Loudness-max
# ---------------------------------------------------------------------------

def analyze_loudness(
    y: np.ndarray,
    sr: int,
    window_seconds: float = 30.0,
    hop_seconds: float = 0.5,
    top_k: int = 5,
) -> list[Candidate]:
    """Slide a window over RMS energy; rank windows by mean loudness.

    Notes
    -----
    Operates on the *audio energy* domain (RMS²), which is the closest cheap
    proxy for what the EBU-R128 momentary-loudness trace would yield. We
    avoid spawning ffmpeg here so the pipeline can be a single Python
    process if the caller prefers.
    """
    import librosa

    duration = len(y) / sr
    if duration < window_seconds:
        return [Candidate(start_seconds=0.0, score=1.0, features={"rms": 1.0})]

    # 100ms hop for the inner RMS frame; 0.5s hop for the outer window.
    hop_frame = int(sr * 0.1)
    rms = librosa.feature.rms(y=y, hop_length=hop_frame)[0]
    energy = rms ** 2

    frames_per_second = sr / hop_frame
    win_frames = int(window_seconds * frames_per_second)
    hop_step_frames = max(1, int(hop_seconds * frames_per_second))

    if win_frames >= len(energy):
        return [Candidate(start_seconds=0.0, score=1.0, features={"rms": 1.0})]

    # Cumulative-sum trick for O(N) sliding sum.
    cum = np.concatenate([[0.0], np.cumsum(energy)])
    starts = np.arange(0, len(energy) - win_frames + 1, hop_step_frames)
    sums = cum[starts + win_frames] - cum[starts]
    means = sums / win_frames

    score_norm = _normalise(means)
    order = np.argsort(score_norm)[::-1][:top_k]

    candidates: list[Candidate] = []
    for idx in order:
        frame_idx = starts[idx]
        start_sec = frame_idx / frames_per_second
        candidates.append(
            Candidate(
                start_seconds=float(start_sec),
                score=float(score_norm[idx]),
                features={"rms_energy_mean": float(means[idx])},
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# T2 — Multi-feature scoring
# ---------------------------------------------------------------------------

def analyze_features(
    y: np.ndarray,
    sr: int,
    audio_type: str = "vocal",
    window_seconds: float = 30.0,
    hop_seconds: float = 0.5,
    top_k: int = 5,
) -> list[Candidate]:
    """Score windows using a weighted blend of four signals.

    Parameters
    ----------
    audio_type:
        One of ``vocal``, ``melodic``, ``percussive``. Selects the weight
        profile. Defaults to ``vocal`` because most user content has voice.
    """
    import librosa

    duration = len(y) / sr
    if duration < window_seconds:
        return [Candidate(start_seconds=0.0, score=1.0, features={})]

    weights = _WEIGHTS.get(audio_type, _WEIGHTS["vocal"])

    # Frame-level features at 100ms granularity.
    hop = int(sr * 0.1)
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    contrast = np.mean(librosa.feature.spectral_contrast(y=y, sr=sr, hop_length=hop), axis=0)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop)[0]

    # Onset density — count onsets per outer-window via convolution of a
    # binary onset-mask with a window of the right size.
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop)
    onset_mask = np.zeros(len(rms), dtype=float)
    onset_frames_clipped = onset_frames[onset_frames < len(onset_mask)]
    onset_mask[onset_frames_clipped] = 1.0

    fps = sr / hop  # frames per second
    win_frames = int(window_seconds * fps)
    step = max(1, int(hop_seconds * fps))
    if win_frames >= len(rms):
        return [Candidate(start_seconds=0.0, score=1.0, features={})]

    # Sliding mean via cumulative sum, applied to each feature.
    def sliding_mean(arr: np.ndarray) -> np.ndarray:
        cum = np.concatenate([[0.0], np.cumsum(arr)])
        starts = np.arange(0, len(arr) - win_frames + 1, step)
        return (cum[starts + win_frames] - cum[starts]) / win_frames

    rms_w = sliding_mean(rms)
    contrast_w = sliding_mean(contrast)
    centroid_w = sliding_mean(centroid)
    onset_w = sliding_mean(onset_mask)  # this becomes onsets-per-frame

    # Normalise each feature to [0, 1] within this song.
    rms_n = _normalise(rms_w)
    contrast_n = _normalise(contrast_w)
    centroid_n = _normalise(centroid_w)
    onset_n = _normalise(onset_w)

    score = (
        weights["rms"] * rms_n
        + weights["contrast"] * contrast_n
        + weights["onset"] * onset_n
        + weights["centroid"] * centroid_n
    )

    starts = np.arange(0, len(rms) - win_frames + 1, step)
    order = np.argsort(score)[::-1][:top_k]
    candidates: list[Candidate] = []
    for idx in order:
        frame_idx = starts[idx]
        start_sec = float(frame_idx / fps)
        candidates.append(
            Candidate(
                start_seconds=start_sec,
                score=float(score[idx]),
                features={
                    "rms": round(float(rms_n[idx]), 3),
                    "contrast": round(float(contrast_n[idx]), 3),
                    "onset": round(float(onset_n[idx]), 3),
                    "centroid": round(float(centroid_n[idx]), 3),
                    "audio_type": audio_type,
                },
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# T3 — Structural chorus detection (SSM)
# ---------------------------------------------------------------------------

def analyze_structural(
    y: np.ndarray,
    sr: int,
    window_seconds: float = 30.0,
    hop_seconds: float = 0.5,
    top_k: int = 5,
) -> list[Candidate]:
    """Detect the most repeated segment via self-similarity.

    The chorus is, by definition, the section the song returns to. We build
    a chroma-based recurrence matrix and find segments whose chroma profile
    matches multiple other segments. Among those repeats we then rank by
    energy so the loudest occurrence is selected.

    Notes
    -----
    This is intentionally not a full music-structure-analysis pipeline —
    that would need MSAF or a dedicated model. The SSM heuristic gets the
    chorus right on canonical verse-chorus pop, and falls back gracefully
    to features-style ranking when the song has no clear repeats.
    """
    import librosa

    duration = len(y) / sr
    if duration < window_seconds:
        return [Candidate(start_seconds=0.0, score=1.0, features={})]

    # Beat-synchronous chroma reduces noise and shrinks the SSM.
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    if len(beats) < 4:
        # No reliable beat grid — fall back to features-style.
        return analyze_features(y, sr, audio_type="vocal", window_seconds=window_seconds, hop_seconds=hop_seconds, top_k=top_k)

    chroma_sync = librosa.util.sync(chroma, beats, aggregate=np.median)
    # Recurrence matrix — boolean, symmetric, off-diagonal hits indicate repetition.
    rec = librosa.segment.recurrence_matrix(chroma_sync, mode="affinity", sym=True)

    # For each beat-segment, count how strongly it repeats elsewhere. Then
    # map that back to time and slide the 30s window over a "repetition
    # score".  ``librosa.util.sync`` adds a leading segment from t=0 to the
    # first beat, so the segment count is ``len(beats) + 1`` and we must
    # build a matching time anchor list.
    rep_score_per_segment = rec.sum(axis=1)
    beat_times = librosa.frames_to_time(beats, sr=sr)
    segment_times = np.concatenate([[0.0], beat_times])
    # If lengths still mismatch (rare versions of librosa), align by
    # truncating to the shorter axis to stay safe.
    n = min(len(segment_times), len(rep_score_per_segment))
    segment_times = segment_times[:n]
    rep_score_per_segment = rep_score_per_segment[:n]

    # Build a continuous repetition score over time by interpolating
    # between segment anchors — effectively a step function on a 100ms grid.
    grid_t = np.arange(0.0, duration, 0.1)
    rep_score = np.interp(grid_t, segment_times, rep_score_per_segment, left=0, right=0)

    # Add energy as a tiebreaker so the loudest occurrence wins.
    hop = int(sr * 0.1)
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    rms_grid = rms[: len(rep_score)] if len(rms) >= len(rep_score) else np.pad(rms, (0, len(rep_score) - len(rms)))

    rep_n = _normalise(rep_score)
    rms_n = _normalise(rms_grid)
    composite = 0.7 * rep_n + 0.3 * rms_n

    fps_grid = 10.0  # 100ms grid
    win_frames = int(window_seconds * fps_grid)
    step = max(1, int(hop_seconds * fps_grid))
    if win_frames >= len(composite):
        return analyze_features(y, sr, audio_type="vocal", window_seconds=window_seconds, hop_seconds=hop_seconds, top_k=top_k)

    cum = np.concatenate([[0.0], np.cumsum(composite)])
    starts = np.arange(0, len(composite) - win_frames + 1, step)
    sums = cum[starts + win_frames] - cum[starts]
    means = sums / win_frames

    score_norm = _normalise(means)
    order = np.argsort(score_norm)[::-1][:top_k]
    candidates: list[Candidate] = []
    for idx in order:
        start_sec = float(starts[idx] / fps_grid)
        candidates.append(
            Candidate(
                start_seconds=start_sec,
                score=float(score_norm[idx]),
                features={"repetition_score": round(float(rep_n[starts[idx]]), 3)},
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Beat alignment
# ---------------------------------------------------------------------------

def align_to_beat(start_seconds: float, y: np.ndarray, sr: int, max_drift: float = 1.0) -> float:
    """Snap a candidate start to the nearest beat within ``max_drift`` seconds.

    Falls back to the original time if beat tracking is unreliable.
    """
    import librosa

    try:
        _, beats = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beats, sr=sr)
        if len(beat_times) == 0:
            return start_seconds
        idx = int(np.argmin(np.abs(beat_times - start_seconds)))
        candidate = float(beat_times[idx])
        if abs(candidate - start_seconds) <= max_drift:
            return candidate
        return start_seconds
    except Exception:
        return start_seconds


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def analyze(
    y: np.ndarray,
    sr: int,
    algorithm: Algorithm = "features",
    audio_type: str = "vocal",
    window_seconds: float = 30.0,
    top_k: int = 5,
) -> list[Candidate]:
    """Dispatch to the requested algorithm."""
    if algorithm == "loudness":
        return analyze_loudness(y, sr, window_seconds=window_seconds, top_k=top_k)
    if algorithm == "features":
        return analyze_features(y, sr, audio_type=audio_type, window_seconds=window_seconds, top_k=top_k)
    if algorithm == "structural":
        return analyze_structural(y, sr, window_seconds=window_seconds, top_k=top_k)
    raise ValueError(f"Unknown algorithm: {algorithm!r}")
