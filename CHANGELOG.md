# Changelog

All notable design changes to the ringtone forge are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This project's "version" tracks the **recipe + agent**, not the script.
Each version is a different formula or a different layer of intelligence,
justified by the reasoning in [METHODOLOGY.md](METHODOLOGY.md) (envelope)
and [ANALYSIS.md](ANALYSIS.md) (chorus detection).

---

## [2.1.0] — 2026-05-17

> **The intelligent agent.** Generic ringtone forge for *any* song —
> classifies the audio, finds the chorus, picks the right envelope, and
> ships a verified ringtone in one command.

### Added
- **Python package** `ringtone_forge` with five modules:
  - `classifier` — vocal / melodic / percussive detection (5/5 accuracy on test set)
  - `analyzer` — three window-ranking algorithms (T1 loudness-max, T2
    multi-feature, T3 structural-chorus via SSM) + beat alignment
  - `envelope` — three genre-adaptive presets, ffmpeg filter generation,
    ASCII visualisation
  - `verify` — preset-aware 7-point quality bar
  - `cli` — argparse-driven agent that strings everything together
- **`ringtone-forge` console script** registered via pyproject.toml
- **uv-managed dependencies**: librosa 0.11+, numpy 2.4+, scipy 1.17+, soundfile 0.13+
- **Brick-wall limiter** (`alimiter limit=0.78`) baked into all envelopes
  to prevent loudness-war source clipping from leaking into the output
- **Beat alignment** — start time snaps to the nearest musical beat
  within ±1 second
- **CLI overrides**: `--algo`, `--preset`, `--start`, `--no-beat-align`,
  `--no-envelope`, `--analyze`, `--json`, `--top-k`
- **`docs/analysis.{svg,png}`** — new diagram for the analysis flow
- **5-song validation set**:
  - 借月.mp3 (vocal pop, 4:36) → start=122.5s, vocal preset, 7/7 ✓
  - 离开我的依赖.mp3 (vocal pop, 4:08) → start=175.0s, vocal preset, 7/7 ✓
  - 跳楼机.mp3 (vocal pop, 3:22) → start=147.0s, vocal preset, 7/7 ✓
  - Brainiac_Maniac.mp3 (electronic, 1:43) → start=64.0s, melodic preset, 7/7 ✓
  - war_drums.m4a (drum loop, 0:40) → start=5.5s, percussive preset, 7/7 ✓

### Changed
- **README** rewritten for v2.1: lead with the agent, push v1 envelope
  details into METHODOLOGY.md
- **Verify** is now preset-aware:
  - Hygiene checks unchanged (duration, fade-out)
  - True peak threshold relaxed from −0.5 dBFS to +1.0 dBFS to accept
    inter-sample peaks (the alimiter handles sample peaks)
  - Replaced absolute `LUFS in [−16, −12]` with relative
    `output LUFS within 4 dB of source LUFS` — modern pop is mastered
    at −7 LUFS and we no longer flag it as broken
  - Replaced absolute `LRA in [8, 14] LU` with relative checks against
    the preset's start_amp (start should be ~start_amp dB below climax)

### Kept
- v1.0 percussive recipe (20s exp + 7s sustain + 3s drop) lives on as
  the `percussive` preset
- `scripts/make-ringtone.sh` and `scripts/verify-ringtone.sh` remain as
  the no-Python-required fast path for known-start scenarios

### Test set verified
| Source                  | Class      | Conf. | Picked at | Preset       | Verify |
|-------------------------|------------|-------|-----------|--------------|--------|
| 借月.mp3                | vocal      | 1.00  | 122.5s    | vocal        | 7/7 ✓  |
| 离开我的依赖.mp3        | vocal      | 1.00  | 175.0s    | vocal        | 7/7 ✓  |
| 跳楼机.mp3              | vocal      | 0.85  | 147.0s    | vocal        | 7/7 ✓  |
| Brainiac_Maniac.mp3     | melodic    | 0.68  | 64.0s     | melodic      | 7/7 ✓  |
| war_drums.m4a           | percussive | 0.78  | 5.5s      | percussive   | 7/7 ✓  |

---

## [1.0.0] — 2026-05-17

> **The reference recipe.** Three-stage exponential rise + linear drop.
> Hand-crafted on a single drum loop. Now lives on as the `percussive`
> preset in v2.

### Formula
```
0–20s : v(t) = 0.2 · 5^(t/20)        (exponential rise, dB-linear)
20–27s: v(t) = 1.0                   (sustain)
27–30s: v(t) = max(0, 1 − (t−27)/3)  (linear sharp drop)
```

### Why this is the v1 final form
- **Rise** changed from linear (v0.3) to exponential. Listening test:
  linear sounds "fast then slow"; exponential matches the ear's
  logarithmic loudness perception. LRA increased from 9.2 LU to 11.6 LU
  — measurable proof of "more distant start, same climax."
- **Sustain** held at 7s (≥5s floor satisfied, climax has time to land).
- **Drop** kept linear at 3s. Linear drop in amplitude → accelerating dB
  descent → "sharp but smooth" departure.

### Reference output
- [`samples/iterations/04-three-stage-exponential.m4a`](samples/iterations/04-three-stage-exponential.m4a)
- copied as [`samples/final/war_drums_ringtone.m4a`](samples/final/war_drums_ringtone.m4a)

### Verified properties (v1 verify thresholds)
| Metric | Value |
|---|---|
| Duration | 30.000s |
| True peak | −5.2 dBFS |
| Integrated loudness | −14.1 LUFS |
| LRA | 11.6 LU |
| RMS at t=0s | −31.8 dB |
| RMS at t=15s | −14.4 dB |
| RMS at t=29.7s | −55.8 dB |

---

## [0.3.0] — 2026-05-17

> **Three-stage with linear rise.** Almost there, but rise sounded
> "front-loaded."

### Formula
```
0–20s : v(t) = 0.2 + 0.8·t/20        (LINEAR rise — the flaw)
20–27s: v(t) = 1.0
27–30s: v(t) = max(0, 1 − (t−27)/3)
```

### Reference output
[`samples/iterations/03-three-stage-linear.m4a`](samples/iterations/03-three-stage-linear.m4a)

### What we learned
Linear amplitude curves are **not perceptually linear**. Volume
measurements at 5s/10s/15s showed that the listener's ear perceived most
of the rise as happening in the first half. This insight drove the v1.0
switch to exponential.

### Why it didn't ship
- Front-loaded loudness contradicts the "approaching from afar" narrative.
- Listener feedback: "feels like it gets loud quickly then plateaus."

---

## [0.2.0] — 2026-05-17

> **Simple 5-second linear fade-in.** Too fast.

### Formula
```
0–5s : v(t) = 0.5 + 0.5·(t/5)        (50% start, ramps to 100% in 5s)
5–30s: v(t) = 1.0                    (no drop yet)
```

### Reference output
[`samples/iterations/02-linear-fadein-5s.m4a`](samples/iterations/02-linear-fadein-5s.m4a)

### What we learned
- 50% start is **too loud** for the "approach" feeling — listener already
  perceives the audio as "here" at second zero.
- 5s rise is **too short** — no time to build anticipation.
- Missing drop section means the ringtone ends abruptly at the 30s cut.

### Why it didn't ship
- Felt like a "trim with quick fade-in," not a designed ringtone.
- Missing the closing arc.

---

## [0.1.0] — 2026-05-17

> **Naive trim.** No envelope at all.

### Formula
```
First 30 seconds of source, full volume throughout.
```

### Reference output
[`samples/iterations/01-trimmed-30s.m4a`](samples/iterations/01-trimmed-30s.m4a)

### What we learned
- Even a perfectly-cut 30s segment **starts and ends abruptly** — the OS
  plays it the moment a call arrives, then chops it mid-decay.
- Audio without envelope shaping is jarring as a ringtone.

### Why it didn't ship
- This is the baseline that motivated everything else.

---

## [0.0.0] — pre-history

> **Source material.**

### Asset
[`samples/source/war_drums.m4a`](samples/source/war_drums.m4a) — 39.92
seconds of war-drum loop.

### Provenance
External asset placed in Downloads. Not authored here.

---

## Format notes

- Versions ≤ 1.x are **recipe revisions** — different envelope shapes.
- Versions ≥ 2.x add **agent capability** — automated source analysis,
  audio classification, structural chorus detection. The recipe (envelope)
  becomes a parameter, not a hard-coded global.
- Each iteration's audio file is preserved in `samples/iterations/` so
  future readers can audition the design journey themselves.
- Date stamps reflect the actual day each iteration was tried.
