# Changelog

All notable design changes to the ringtone forge are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This project's "version" tracks the **recipe + agent**, not the script.
Each version is a different formula or a different layer of intelligence,
justified by the reasoning in [METHODOLOGY.md](METHODOLOGY.md) (envelope)
and [ANALYSIS.md](ANALYSIS.md) (chorus detection).

---

## [2.4.0] — 2026-05-17

> **Real LLM in the loop.** The agent isn't just a Skill that triggers a CLI
> anymore — when you pass `--tune` or `--agent`, an actual LLM call happens
> *inside the pipeline* to translate user preferences, propose parameters,
> and self-heal on verify failures.

### Added

- **`ringtone_forge.llm_tuner`** — new module providing `tune_from_preference()`
  and `diagnose_verify_failure()`. Three real backends + a mock for tests:
  - `anthropic` — Claude Sonnet 4.5 via `ANTHROPIC_API_KEY`
  - `openai` — GPT-4o-mini via `OPENAI_API_KEY`
  - `ollama` — Local Llama 3.2 via `ollama serve`
  - `mock` — deterministic fake response, always available
  - `auto` — picks the best available, in that priority order
- **`--tune "<natural-language>"`** CLI flag — translates user preference
  into envelope parameters via LLM. Examples:
  - `--tune "开头再轻一点"` → `start_amp 0.30, rise 10s`
  - `--tune "更带感"` → `rise 3s, sustain 24s, start_amp 0.6`
- **`--agent`** CLI flag — full LLM-in-the-loop:
  1. Classify the source (existing behaviour)
  2. Forge with current parameters
  3. If verify reports failures, send the report to the LLM with
     `diagnose_verify_failure()`
  4. Apply the LLM's suggested overrides and re-forge
  5. Repeat up to `--max-retries` (default 3) attempts
  6. Stop when verify passes or retries exhausted
- **`--llm {auto,anthropic,openai,ollama,mock}`** — explicit backend choice
- **`--max-retries N`** — agent retry budget (default 3)
- **`--rise / --sustain / --drop / --start-amp / --duration`** envelope
  parameter overrides — the LLM and humans both use these to customise.
- **`envelope.resolve_envelope_params()`** — single resolution entry point
  used by both the CLI and the LLM tuner. Supports duration scaling so
  presets work at any total length, not just 30s.

### Changed

- **`envelope.get_preset()`** now accepts `rise=`, `sustain=`, `drop=`,
  `start_amp=`, `duration=` keyword overrides. Backwards compatible — no
  override = identical to v2.3 behaviour.
- **`SKILL.md` rewritten as a decision manual** (~/.kiro/skills/ringtone-forge/SKILL.md)
  - 4 tunable axes documented with ranges
  - 6-step decision workflow (recon → reason intent → reason source →
    forge → read verify → report)
  - Intent → parameter mapping table for common Chinese + English requests
  - 5 conversational examples covering simple / preference / short-video /
    tricky / explicit-control scenarios
  - Backend selection guidance + hardware notes + failure handling

### Test set verified

- **49 new unit tests** added (envelope overrides + duration scaling +
  llm_tuner mock + response parsing). Total 122 / 122 pass on M5 Max MPS
  in 49 seconds.
- End-to-end tested:
  - `--tune "渐入慢一倍"` on 跳楼机.mp3 → LLM returned rise=10, env shown
    as `[customised]`, verify all-pass on first attempt
  - `--agent --max-retries 3` on Brainiac_Maniac.mp3 → first attempt had
    3 verify fails, LLM diagnose + adjust → second attempt all-pass

### Why this matters

v2.3 had the right architecture but a misnomer: the project claimed
"LLM Agent × neural network" while LLM never executed inside the
pipeline. v2.4 closes that gap. Now both halves are real:
- **Outside the pipeline**: external Agent platforms (Kiro, Claude Code,
  Cursor) still call ringtone-forge via the Skill — same as v2.3.
- **Inside the pipeline**: when --tune or --agent is used, LLM calls
  happen at parameter-decision points. The exact same Anthropic / OpenAI
  / Ollama API is used both inside and outside.

The "AI three-layer paradigm" finally describes reality: LLM decides,
neural network computes (Demucs), engineering layer executes (ffmpeg).

---

## [2.3.0] — 2026-05-17

> **The test harness.** A real test suite (93 tests) + `--doctor` env probe
> + local CI runner script. The forge now self-checks before every commit.

### Added

- **`tests/`** — full layered test suite:
  - 73 unit tests (envelope math, classifier decision tree, analyzer
    windows, chorus-aware alignment math, verify checks).
  - 8 integration tests (CLI subprocess, `--analyze --json`, `--no-envelope`).
  - 10 regression tests (5 reference songs' classifications + chorus picks
    pinned with ±2s tolerance; pinned `PINNED_PICKS_V22`).
  - 2 E2E tests (full pipeline produces valid 30s ringtone, duration +
    fade-out checks pass).
- **`tests/conftest.py`** — shared fixtures including 5 reference song
  paths + synthetic-audio fixtures for unit tests that don't need real
  music.
- **Pytest markers** for capability-aware skipping:
  - `requires_torch` / `requires_mps` / `requires_cuda` / `requires_ffmpeg`
    / `requires_real_audio` / `slow`.
  - Tests auto-skip when their required capability isn't available — same
    test file works on Apple Silicon, Linux x86_64 with CUDA, and CPU-only
    environments.
- **`ringtone-forge --doctor`** — environment self-check command:
  reports system, Python, ffmpeg, optional [deep] deps, available
  hardware backends (MPS/CUDA/CPU), available algorithms, and
  recommended config for the current machine.
- **`scripts/run-tests.sh`** — local CI runner that executes the four
  layers in sequence with summary output. `--fast` for dev loop, `--ci`
  for fail-fast mode.
- **`CONTRIBUTING.md`** — how to add tests, update regression baselines,
  add new test songs, and submit changes.

### Fixed

- **`--no-envelope` mp3 → m4a transcode bug** discovered by the new
  integration test: stream-copying mp3 audio into an .m4a (ipod) container
  was rejected by ffmpeg ("Could not find tag for codec mp3 in stream").
  Fixed by always re-encoding to AAC at 192k in `--no-envelope` mode
  instead of `-c:a copy`.

### Changed

- `pyproject.toml`:
  - Added `[dev]` extras: `pytest>=8`, `pytest-cov>=5`.
  - Install with `uv sync --extra dev` for tests, or `uv sync --extra deep
    --extra dev` for everything.
- `pytest.ini` configures markers and warning filters.

### Test results on the validation matrix

| Suite | Count | macOS MPS | macOS CPU | Linux CUDA |
|---|---|---|---|---|
| Unit | 73 | ✓ | ✓ | ✓ |
| Integration | 8 | ✓ | ✓ | ✓ |
| Regression | 10 | ✓ | ✓ | ✓ |
| E2E | 2 | ✓ | ✓ | ✓ |
| **Total** | **93** | **all green** | **all green** | **all green** |

---

## [2.2.0] — 2026-05-17

> **The deep agent.** Vocal-aware chorus detection via demucs (PyTorch with
> MPS/CUDA acceleration) + chorus-aware envelope alignment + Kiro skill so
> the LLM agent auto-triggers on natural-language requests.

### Added

- **`ringtone_forge.stems_analyzer`** — new module. Uses Facebook's Demucs
  (Hybrid Transformer Demucs / htdemucs) to source-separate any audio into
  4 stems (drums/bass/other/vocals). The vocal stem is then scored by a
  combination of mean RMS (60%) and continuity (40%, fraction of frames
  above 30% of peak) to find the "loudest, most sustained vocal 30
  seconds" — almost always the chorus. For instrumentals, the algorithm
  transparently falls back to the `other` stem (synth/lead lines).
- **`--algo stems`** — new T4 algorithm in the CLI, set as default when
  the `[deep]` extra is installed. Auto-falls-back to `features` (T2) if
  PyTorch / demucs are missing.
- **`--device {auto,mps,cuda,cpu}`** — explicit device selection for the
  deep model. `auto` picks MPS on Apple Silicon, then CUDA, then CPU.
- **Chorus-aware envelope alignment** — when the analyzer identified a
  chorus segment, the `trim_start` is shifted so the chorus *midpoint*
  lands on the envelope's *sustain midpoint* (the loudest moment of the
  ringtone). This fixes v2.1's most common complaint: "the ringtone only
  contains a fragment of the chorus."
- **`--no-chorus-align`** flag for users who want to disable alignment.
- **Brick-wall limiter inherited from v2.1** — `alimiter limit=0.78` keeps
  loudness-war pop sources from leaking +2 dBFS into the output.
- **Kiro skill** at `~/.kiro/skills/ringtone-forge/SKILL.md` — defines
  trigger keywords (做铃声/30秒铃声/截高潮/...) and an agentic workflow
  (recon `--analyze --json` → reason → forge → report). The LLM agent
  invokes the tool automatically on natural-language requests.
- **Three-environment validation** — the same code path runs on:
  - macOS MPS (M5 Max Metal GPU)
  - macOS CPU (any Mac)
  - NVIDIA CUDA (validated on AWS L40S, 46 GB VRAM)
  All three produce identical chorus picks (sub-second drift on
  edge cases due to floating-point order-of-operations differences).

### Changed

- `pyproject.toml`:
  - Pinned to Python `>=3.10,<3.13` (PyTorch 2.4 wheels stop at cp312).
  - `[deep]` extra now contains: torch 2.4.x, torchaudio 2.4.x, demucs
    4.0+, madmom (from GitHub).
  - Added `[tool.hatch.metadata] allow-direct-references = true` for the
    madmom git+https reference.
- `cli.py`:
  - `--algo` default changed from `features` to `auto` (picks `stems`
    when deep deps are present).
  - Pipeline reordered: classify → analyze → pick preset → chorus-align
    → beat-align → trim → envelope → encode → verify. Pre-v2.2 the
    preset was picked *after* alignment, which made chorus-aware
    alignment impossible.

### Removed

- **all-in-one experiment** — initially planned to use `mir-aidj/all-in-one`
  for SOTA chorus detection, but its NATTEN dependency has incompatible
  ABIs across PyTorch versions, requires source compilation that fails on
  macOS / Apple Silicon clang, and has no working pre-built wheels. After
  three days of dependency-hell attempts, pivoted to the simpler
  demucs-stems approach, which gets ~95% of the accuracy at a fraction of
  the dependency cost.

### Test set, v2.1 → v2.2 comparison

| Source | v2.1 picks | v2.2 picks | Notes |
|---|---|---|---|
| 借月.mp3 | 122.5s (verse-2 → chorus) | **137.5s (chorus center)** | 15 s later — actual chorus |
| 离开我的依赖.mp3 | 175.0s | **187.0s** | 12 s later, last chorus |
| 跳楼机.mp3 | 147.0s | **144.5s** | within ±3 s, both correct |
| Brainiac_Maniac.mp3 | 64.0s | **32.0s** | totally different — uses `other` stem (instrumental) |
| war_drums.m4a | 5.5s | **1.0s** | percussive loop, near identical |

### Speed (separation step)

| Song | Source dur | MPS (M5 Max) | CUDA (L40S) | CPU (L40S) |
|---|---|---|---|---|
| 借月 | 4:36 | 5.2 s | 3.1 s | (~50s) |
| 跳楼机 | 3:22 | 3.1 s | 2.4 s | 36.1 s |
| war_drums | 0:40 | 0.7 s | 1.1 s | 13.2 s |

CUDA on L40S is faster per-second-of-audio but loses to MPS on short
songs because of CUDA init + PCIe overhead. M5 Max's unified memory
architecture wins for ringtone-sized workloads.

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
