# 🔔 ringtone-forge

> A reproducible recipe for crafting **30-second mobile ringtones** from any source audio — codified from real iteration scars.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![ffmpeg](https://img.shields.io/badge/built%20with-ffmpeg-007808.svg)](https://ffmpeg.org/)
[![Status](https://img.shields.io/badge/status-stable-brightgreen.svg)](#)

A ringtone is not just a clip. It's a **20s exponential rise → 7s peak → 3s sharp drop** miniature drama, designed for the human ear's logarithmic loudness perception. This repo encodes that recipe as a reusable script and the reasoning behind every parameter.

---

## TL;DR — The Formula

```
┌─────────────────── 30 seconds total ───────────────────┐
│                                                          │
│   0s ──── 20s ──────────── 27s ──── 30s                 │
│   │       │                │        │                   │
│   │ rise  │   sustain      │ drop   │                   │
│   │ 20s   │   7s           │ 3s     │                   │
│   │       │                │        │                   │
│   20% ─exp→ 100% ──────── 100% ─lin→ 0%                 │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

| Stage | Time | Volume | Curve | Why |
|---|---|---|---|---|
| **Rise** | `0s → 20s` | `20% → 100%` | **Exponential** (`v = 0.2 · 5^(t/20)`) | dB-linear ≈ ear-linear; "approaching from afar" |
| **Sustain** | `20s → 27s` | `100%` | flat | climax breathing room (≥5s) |
| **Drop** | `27s → 30s` | `100% → 0%` | **Linear** (`v = 1 − (t−27)/3`) | front-loaded fast decay = "sharp but smooth" |

Single `ffmpeg` invocation:

```bash
ffmpeg -i input.m4a -t 30 \
  -af "volume='if(lt(t,20), 0.2*pow(5,t/20), if(lt(t,27), 1, max(0, 1-(t-27)/3)))':eval=frame" \
  -c:a aac -b:a 128k output_ringtone.m4a
```

---

## Visualizations

### Volume envelope across 30 seconds
![Volume Curve](docs/volume-curve.png)

### End-to-end pipeline
![Pipeline](docs/pipeline.png)

---

## Quick Start

### Prerequisites
- `ffmpeg` (with `aac` encoder — default on macOS via `brew install ffmpeg`)

### One-liner
```bash
./scripts/make-ringtone.sh path/to/your_audio.m4a
# → produces: your_audio_ringtone.m4a (30s)
```

Specify output path:
```bash
./scripts/make-ringtone.sh input.m4a output.m4a
```

### Verify the output
```bash
./scripts/verify-ringtone.sh output_ringtone.m4a
# Prints: duration, RMS at key timestamps, true peak, integrated loudness
```

---

## Showcase: `war_drums.m4a` → `war_drums_ringtone.m4a`

Source: a 39.9-second war drum loop. The forge crops the most evocative 30s and applies the envelope.

| File | Duration | Description |
|---|---|---|
| [`samples/source/war_drums.m4a`](samples/source/war_drums.m4a) | 39.92s | original |
| [`samples/final/war_drums_ringtone.m4a`](samples/final/war_drums_ringtone.m4a) | 30.00s | **final ringtone** |

The four numbered files in [`samples/iterations/`](samples/iterations/) trace the actual design journey from "naive trim" to "exponential three-stage" — each step driven by listening, measuring, and revising. See [`CHANGELOG.md`](CHANGELOG.md) for the narrative.

---

## Why this exists

Most "fade-in/fade-out" tutorials hand you a one-line filter and walk away. This repo answers the **why** behind each parameter:

- Why 30 seconds (not 25, not 45)?
- Why exponential rise but linear drop?
- Why 20% start (not 0%, not 50%)?
- Why 7s sustain (not 5s, not 12s)?
- How do you measure that the result actually matches the design?

All answered in [**METHODOLOGY.md**](METHODOLOGY.md).

---

## Repo layout

```
ringtone-forge/
├── README.md              ← you are here
├── METHODOLOGY.md         ← design theory & parameter rationale
├── CHANGELOG.md           ← iteration history (v0 → v1.0)
├── LICENSE                ← MIT
├── scripts/
│   ├── make-ringtone.sh   ← one-shot 30s ringtone forge
│   └── verify-ringtone.sh ← measure RMS / LUFS / true peak
├── samples/
│   ├── source/            ← raw source audio
│   ├── iterations/        ← every revision in order
│   └── final/             ← the deliverable
└── docs/
    ├── volume-curve.svg   ← envelope visualization (vector)
    ├── volume-curve.png   ← envelope visualization (raster)
    ├── pipeline.svg       ← end-to-end flow (vector)
    └── pipeline.png       ← end-to-end flow (raster)
```

---

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, ship better ringtones.

---

> *"A ringtone is a 30-second story. It must approach, arrive, and leave — without overstaying its welcome."*
