"""
Audio type classifier — vocal / melodic / percussive.

Different audio types deserve different ringtone treatments:
- vocal      → human voice present, lyrical content. Listener wants the
               climax to land fast. Short rise (5s), long sustain (22s).
- melodic    → instrumental with clear melody (synth lead, orchestral,
               EDM, electronic). Medium rise (12s), medium sustain (15s).
- percussive → drum loops, raw beats, near-static energy curves. Long
               exponential rise (20s) sells the "approaching from afar"
               narrative — that's the v1.0 recipe.

The classifier is a heuristic decision tree on four orthogonal features:
  1. MFCC variance — high variance means the timbre changes across phonemes
     or notes (vocals, melodic). Low variance means a static loop.
  2. Chroma standard deviation — high means the harmony moves (verse to
     chorus, chord changes). Low means tonally static.
  3. Onset rate — events per second. High means a dense electronic/EDM
     texture; medium means typical vocal pop; low can mean either ballad
     vocals or simple drum loops.
  4. Zero-crossing rate — vocal sibilance and consonants push ZCR up;
     pure pitched tones keep it low.

These thresholds were tuned on a real test set:
  借月, 离开我的依赖, 跳楼机 (Mandarin pop vocals)
  Brainiac_Maniac (electronic/synth instrumental)
  war_drums (drum loop, percussive)
The classifier reproduces the human-expected label for all five.

This is intentionally simple — no ML model, no training data, deterministic
output. Edge cases can always be overridden via `--preset` on the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


AudioType = Literal["vocal", "melodic", "percussive"]


@dataclass(frozen=True)
class ClassificationResult:
    """Output of the classifier.

    Attributes
    ----------
    audio_type:
        Best-guess category among ``vocal``, ``melodic``, ``percussive``.
    mfcc_variance:
        Average per-coefficient std-dev of MFCCs 2..13. Vocals and melodic
        material score ~15+; static drum loops score ~10.
    chroma_std:
        Mean per-pitch-class standard deviation of the chromagram. Songs
        with chord progressions sit at 0.27+; static beats sit below 0.25.
    onset_rate:
        Detected onsets per second.  Pop vocals: 2–4; EDM/electronic: 5+;
        slow ballads or simple loops: < 2.
    zero_crossing_rate:
        Mean ZCR. Vocals push it up via consonants and sibilance.
    confidence:
        How clearly the audio fits its assigned bucket, on [0, 1].
    """

    audio_type: AudioType
    mfcc_variance: float
    chroma_std: float
    onset_rate: float
    zero_crossing_rate: float
    confidence: float


def classify(y: np.ndarray, sr: int) -> ClassificationResult:
    """Classify a loaded audio signal.

    Parameters
    ----------
    y : np.ndarray
        Mono audio samples in float32, range roughly [-1, 1].
    sr : int
        Sample rate in Hz.

    Returns
    -------
    ClassificationResult
    """
    # Lazy import — librosa is heavy and we want the package to import fast
    # when only the envelope or verify modules are needed.
    import librosa

    duration = len(y) / sr

    # 1. MFCC variance over coefficients 2..13.
    #    Coefficient 1 is mostly energy, so we drop it. The remaining
    #    coefficients describe spectral shape; their per-frame std-dev is
    #    a good proxy for "how varied is the timbre over time".
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_variance = float(np.mean(np.std(mfcc[1:], axis=1)))

    # 2. Chromagram std-dev — harmony movement.
    chroma = librosa.feature.chroma_stft(y=y, sr=sr)
    chroma_std = float(np.mean(np.std(chroma, axis=1)))

    # 3. Onset rate.
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
    onset_rate = len(onset_frames) / duration if duration > 0 else 0.0

    # 4. Zero-crossing rate.
    zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)))

    # --- Decision tree (ordered by signal strength) -----------------------
    #
    # Step 1: Static-energy / drum-loop content lacks both timbral and
    # harmonic motion. If MFCC variance is low AND chroma is static, it is
    # percussive — even if a few pitched elements show up, the song reads
    # as a beat loop in the listener's ear.
    if mfcc_variance < 12.0 and chroma_std < 0.26:
        audio_type: AudioType = "percussive"
        # Confidence rises as we move further below the dual threshold.
        confidence = float(
            np.clip(0.5 + (12.0 - mfcc_variance) * 0.10 + (0.26 - chroma_std) * 4.0, 0.0, 1.0)
        )

    # Step 2: Dense electronic / synth-driven instrumentals have tons of
    # onsets per second (continuous arpeggios, hi-hat patterns) and HPSS
    # leaks them into the harmonic side, so we cannot rely on
    # harmonic-ratio. We catch them via onset rate.
    elif onset_rate >= 4.5 and zcr < 0.10 and chroma_std < 0.275:
        audio_type = "melodic"
        confidence = float(np.clip(0.5 + (onset_rate - 4.5) * 0.15, 0.0, 1.0))

    # Step 3: Vocal pop. The combination of moderate ZCR (consonants),
    # rich timbre variance (phoneme changes), and chord progressions
    # is the unique fingerprint of the human voice.
    elif zcr >= 0.06 and mfcc_variance >= 14.0 and chroma_std >= 0.26:
        audio_type = "vocal"
        # Vote-style confidence: each of the three thresholds adds margin.
        margin = (
            min((zcr - 0.06) * 10, 0.3)
            + min((mfcc_variance - 14.0) * 0.10, 0.3)
            + min((chroma_std - 0.26) * 5.0, 0.3)
        )
        confidence = float(np.clip(0.55 + margin, 0.0, 1.0))

    # Step 4: Default to melodic (instrumental with melody). It is the
    # safest fallback because the melodic envelope sits between vocal
    # and percussive — being wrong by one bucket here costs the least.
    else:
        audio_type = "melodic"
        confidence = 0.55

    return ClassificationResult(
        audio_type=audio_type,
        mfcc_variance=round(mfcc_variance, 3),
        chroma_std=round(chroma_std, 4),
        onset_rate=round(onset_rate, 3),
        zero_crossing_rate=round(zcr, 4),
        confidence=round(confidence, 3),
    )
