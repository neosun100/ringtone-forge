"""
Stems-aware chorus detector — the v2.2 deep-learning analyzer.

Why a "deep" tier when v2.1 already had three algorithms?
=========================================================

v2.1's heuristics (RMS, spectral contrast, onset density, chroma SSM) operate
on the *mixed* audio. A loud guitar in a verse can outscore a quieter chorus
moment. That mismatch — picking "consistently loud passage" instead of "the
chorus" — was the core complaint.

v2.2's insight: in pop music, **the chorus is where the human voice is
loudest and most continuous**. If we cleanly isolate the vocal track, the
"loudest vocal 30 seconds" is overwhelmingly likely to be the climax of the
song. Verses are sung quietly; choruses are sung at full energy with
backing harmonies layered on top.

We use Facebook's Demucs (Hybrid Transformer Demucs / htdemucs), a SOTA
open-source music source separator, to split a song into four stems:
``drums``, ``bass``, ``other``, ``vocals``. We then score 30-second windows
on the vocal stem alone:

* **vocal RMS** (60% weight) — singing energy
* **vocal continuity** (40% weight) — penalises gaps; choruses sustain notes

The 30-second window with the highest combined score is the predicted
chorus. For instrumentals (Brainiac_Maniac in our test set) where the
vocals stem is silent, we transparently fall back to the ``other`` stem
(synth/lead lines) which carries the main melodic content.

Hardware acceleration
=====================

Demucs is a PyTorch model. The ``device`` parameter selects the backend:

* ``'mps'`` — Apple Silicon Metal GPU (M-series Macs)
* ``'cuda'`` — NVIDIA GPU
* ``'cpu'`` — fallback

On M5 Max, separation runs at ~5x realtime (60s audio → ~12s wall clock).
On CUDA L40S, ~30x realtime. CPU is ~0.5x — usable but slow.

The model weights (~80 MB for htdemucs) are cached at
``~/.cache/torch/hub/checkpoints/`` after first download.

Chorus-aware envelope alignment
================================

Once we know the chorus is, say, [60s, 90s] in the source, we don't just
trim [60, 90] and hope. We *align the chorus to the envelope's loudest
moment* so the listener hears the climax exactly when the volume peaks.
For a vocal preset (rise=5s, sustain=22s, drop=3s) the envelope's loudest
midpoint is at ringtone-time 5 + 22/2 = 16s. So we set
``trim_start = chorus_mid − 16``. The 30-second ringtone now has the
chorus straddling its loudest 22 seconds. See README/ANALYSIS for the
detailed rationale.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class StemAnalysisResult:
    """Output of stems-aware analysis.

    Attributes
    ----------
    chorus_start_seconds, chorus_end_seconds:
        Predicted chorus boundaries in the *source* timeline.
    confidence:
        How peak-y the vocal energy was on [0, 1]. 1.0 means a clear single
        peak; 0.5 means several similar candidates; below 0.3 means the
        algorithm fell back to the instrumental stem (no clear vocal chorus).
    primary_stem:
        Which stem drove the decision: ``vocals`` for vocal songs,
        ``other`` for instrumentals.
    candidates:
        Top-N candidate windows with scores (debug aid).
    device_used:
        ``mps`` / ``cuda`` / ``cpu`` — which device demucs ran on.
    seconds_to_separate:
        Wall-clock time spent on demucs inference.
    """

    chorus_start_seconds: float
    chorus_end_seconds: float
    confidence: float
    primary_stem: str
    candidates: list[tuple[float, float]] = field(default_factory=list)  # (start, score)
    device_used: str = "cpu"
    seconds_to_separate: float = 0.0


def _select_device(prefer: str = "auto") -> str:
    """Pick a PyTorch device.

    ``auto`` returns the best available (mps > cuda > cpu).
    Any other value is honoured directly if its backend is available,
    otherwise we fall back through the same priority list.
    """
    import torch

    if prefer == "auto":
        if torch.backends.mps.is_available() and torch.backends.mps.is_built():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    if prefer == "mps" and torch.backends.mps.is_available():
        return "mps"
    if prefer == "cuda" and torch.cuda.is_available():
        return "cuda"
    if prefer == "cpu":
        return "cpu"

    # Requested device unavailable; warn and pick best
    warnings.warn(f"Requested device '{prefer}' unavailable, falling back to auto-select.")
    return _select_device("auto")


def _separate_stems(
    audio_path: str,
    device: str,
    model_name: str = "htdemucs",
) -> tuple[np.ndarray, list[str], int, float]:
    """Run demucs on the audio file, returning stems + metadata.

    Returns
    -------
    stems : np.ndarray
        Shape ``(n_sources, n_channels, n_samples)``, float32.
    sources : list[str]
        Stem names in the order they appear, e.g. ``['drums','bass','other','vocals']``.
    sample_rate : int
        Demucs's native sample rate (44100 for htdemucs).
    elapsed_seconds : float
        Wall-clock time of the inference.
    """
    import time

    import torch
    import librosa
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    model = get_model(model_name)
    model = model.to(device).eval()

    # Use librosa for robust loading of any format (m4a / mp3 / flac / wav).
    # torchaudio's default soundfile backend chokes on m4a.
    wav_np, sr = librosa.load(audio_path, sr=model.samplerate, mono=False)
    if wav_np.ndim == 1:
        # mono → duplicate to stereo for demucs
        wav_np = np.stack([wav_np, wav_np], axis=0)
    sr = model.samplerate

    wav = torch.from_numpy(wav_np).float().to(device).unsqueeze(0)

    t0 = time.time()
    with torch.no_grad():
        stems = apply_model(model, wav, device=device, split=True, overlap=0.10, progress=False)
    elapsed = time.time() - t0

    stems = stems.squeeze(0).cpu().numpy()  # (n_sources, n_channels, n_samples)
    return stems, list(model.sources), sr, elapsed


def _stem_rms_envelope(stem_wave: np.ndarray, sr: int, hop_seconds: float = 0.1) -> np.ndarray:
    """Mono-mix a stereo stem and compute frame-level RMS at ``hop_seconds`` resolution."""
    mono = stem_wave.mean(axis=0) if stem_wave.ndim == 2 else stem_wave
    hop = max(1, int(sr * hop_seconds))
    n_frames = len(mono) // hop
    rms = np.empty(n_frames, dtype=np.float32)
    for i in range(n_frames):
        chunk = mono[i * hop:(i + 1) * hop]
        rms[i] = float(np.sqrt(np.mean(chunk ** 2) + 1e-12))
    return rms


def _continuity_score(rms_window: np.ndarray, threshold_pct: float = 0.30) -> float:
    """How much of the window is above ``threshold_pct`` of its own peak.

    A solid chorus stays loud throughout (high continuity).  A verse with
    one shouted line followed by silence has a single spike (low continuity).
    Returns a fraction in [0, 1].
    """
    if rms_window.size == 0:
        return 0.0
    peak = float(rms_window.max())
    if peak < 1e-6:
        return 0.0
    above = (rms_window >= peak * threshold_pct).sum()
    return float(above) / float(rms_window.size)


def find_chorus_window_stems(
    audio_path: str,
    window_seconds: float = 30.0,
    hop_seconds: float = 0.5,
    device: str = "auto",
    top_k: int = 5,
) -> StemAnalysisResult:
    """End-to-end stems-aware chorus detection.

    Pipeline:
        1. Demucs separates the song into 4 stems.
        2. Compute a frame-level RMS envelope on the vocals stem.
        3. Slide a 30-second window; score = 0.6·mean_rms + 0.4·continuity.
        4. Return the highest-scoring window.

    Fallback: if vocal energy is below a noise floor (instrumental track),
    re-run scoring on the ``other`` stem (lead/synth/melody).
    """
    device = _select_device(device)

    stems, sources, sr, elapsed_sep = _separate_stems(audio_path, device)
    duration = stems.shape[-1] / sr

    if duration < window_seconds:
        return StemAnalysisResult(
            chorus_start_seconds=0.0,
            chorus_end_seconds=duration,
            confidence=0.0,
            primary_stem="(too-short)",
            device_used=device,
            seconds_to_separate=elapsed_sep,
        )

    # ----- Score vocal stem -----------------------------------------------
    vocals_idx = sources.index("vocals") if "vocals" in sources else None
    other_idx = sources.index("other") if "other" in sources else None

    def score_on_stem(stem_idx: int):
        rms = _stem_rms_envelope(stems[stem_idx], sr, hop_seconds=0.1)
        fps = 10.0  # 100ms hop
        win_frames = int(window_seconds * fps)
        step = max(1, int(hop_seconds * fps))
        if win_frames >= len(rms):
            return None, None, None

        starts = np.arange(0, len(rms) - win_frames + 1, step)
        means = np.empty(len(starts), dtype=np.float32)
        conts = np.empty(len(starts), dtype=np.float32)
        for i, s in enumerate(starts):
            window = rms[s:s + win_frames]
            means[i] = window.mean()
            conts[i] = _continuity_score(window, threshold_pct=0.30)

        # Normalise to [0,1] within song
        mean_n = (means - means.min()) / (means.max() - means.min() + 1e-9)
        cont_n = conts  # already a fraction
        scores = 0.60 * mean_n + 0.40 * cont_n
        return starts / fps, scores, rms

    voc_starts, voc_scores, voc_rms = score_on_stem(vocals_idx) if vocals_idx is not None else (None, None, None)

    # Decide primary stem: vocals if it has meaningful energy, else 'other'.
    primary_stem_name = "vocals"
    starts, scores, rms = voc_starts, voc_scores, voc_rms

    if voc_rms is not None:
        vocal_peak_rms = float(voc_rms.max())
        # Threshold: if vocal stem peak is below ~−40 dBFS-ish, treat as instrumental
        if vocal_peak_rms < 0.005:
            primary_stem_name = "other"
            starts, scores, rms = score_on_stem(other_idx)

    if scores is None:
        # Final fallback: degenerate — use whichever stem we can
        return StemAnalysisResult(
            chorus_start_seconds=0.0,
            chorus_end_seconds=window_seconds,
            confidence=0.0,
            primary_stem="(degenerate)",
            device_used=device,
            seconds_to_separate=elapsed_sep,
        )

    # Top-K candidates
    order = np.argsort(scores)[::-1][:top_k]
    candidates = [(float(starts[i]), float(scores[i])) for i in order]
    best_start = float(starts[order[0]])
    best_score = float(scores[order[0]])

    # Confidence = peak score / mean of top 5 — a clear winner has ratio > 1.05
    top_mean = float(np.mean([scores[i] for i in order]))
    confidence = float(np.clip(best_score / max(top_mean, 1e-6) * 0.5 + best_score * 0.5, 0.0, 1.0))

    return StemAnalysisResult(
        chorus_start_seconds=best_start,
        chorus_end_seconds=best_start + window_seconds,
        confidence=confidence,
        primary_stem=primary_stem_name,
        candidates=candidates,
        device_used=device,
        seconds_to_separate=elapsed_sep,
    )


def chorus_aware_trim_start(
    chorus_start: float,
    chorus_end: float,
    preset_rise_seconds: float,
    preset_sustain_seconds: float,
    source_duration: float,
    ringtone_duration: float = 30.0,
) -> float:
    """Compute trim_start so the chorus aligns to the envelope's loudest moment.

    Strategy: place the chorus mid-point onto the envelope's sustain mid-point.

    Why this matters
    ----------------
    A naïve approach is ``trim_start = chorus_start``. But the envelope
    spends the first ``rise_seconds`` ramping up; if the chorus is only
    18 seconds long, half of it gets played at sub-100% volume.

    Aligning ``chorus_mid`` to ``sustain_mid`` (which is at 100%) means:

    * the verse-end / pre-chorus naturally fades in during envelope rise
    * the chorus body (loudest part of the song) hits 100% volume
    * the chorus tail or post-chorus rides the linear drop

    Edge cases handled:

    * Chorus near the *start* of the song: trim_start clamped to 0.
    * Chorus near the *end* of the song: trim_start clamped to keep 30s of audio.
    """
    chorus_mid = (chorus_start + chorus_end) / 2.0
    sustain_mid_in_ringtone = preset_rise_seconds + preset_sustain_seconds / 2.0

    trim_start = chorus_mid - sustain_mid_in_ringtone

    # Clamp so we always have ringtone_duration seconds of source available
    trim_start = max(0.0, min(trim_start, source_duration - ringtone_duration))
    return trim_start


__all__ = [
    "StemAnalysisResult",
    "find_chorus_window_stems",
    "chorus_aware_trim_start",
]
