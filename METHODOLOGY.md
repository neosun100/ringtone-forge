# Methodology — The Reasoning Behind the Recipe

This document codifies **every parameter choice** in the 30-second ringtone formula. Each section answers a "why" question that arose during real iteration.

---

## 1. Why 30 seconds?

Mobile operating systems clip incoming-call audio at **30 seconds maximum**:

| Platform | Ringtone limit |
|---|---|
| iOS (`.m4r`) | 30s hard cap |
| Android | typically 30–40s, varies by ROM |
| WeCom / Slack notification | 5–30s |

So 30s is **the maximum useful length**. Anything shorter wastes the OS's allowance; anything longer gets truncated mid-decay (which sounds broken).

**Decision: 30.000s exactly.**

---

## 2. Why three stages?

A ringtone is a **micro-narrative**. It needs:

- An **opening** that catches attention without startling
- A **climax** loud enough to be heard across the room
- A **closing** that signals "the alert is done" (not "the speaker died")

Mapping these to time:

| Narrative beat | Audio mechanism |
|---|---|
| Approach | gradual volume rise |
| Arrival | sustained peak |
| Departure | controlled decay |

**Decision: rise → sustain → drop, three contiguous segments.**

---

## 3. Why 20-second rise?

We tried multiple lengths during iteration:

| Rise duration | Listening verdict |
|---|---|
| 5s | "feels rushed; barely starts before it's already loud" |
| 12s (symmetric) | "okay, but no time to build atmosphere" |
| **20s** | **"approaches from afar, builds anticipation, arrives just in time"** |
| 25s | "sustain too short; climax feels truncated" |

**Constraint:** sustain must be ≥5s (see §5), drop must be ≥3s (§6). So rise ≤ 22s.
**Sweet spot:** 20s, leaving 7s sustain + 3s drop = 30s exactly.

---

## 4. Why exponential rise (not linear)?

This is the single most consequential design choice, and the lesson behind v1.0.

### The trap of linear amplitude

Our v0.3 used `v(t) = 0.2 + 0.8·t/20` — a straight line in amplitude. Plotted on paper, perfectly even. But ears don't hear amplitude — **they hear loudness, which is logarithmic**.

| Time | Linear amplitude | Equivalent dB |
|---|---|---|
| 0s | 20% | −14 dB |
| 5s | 40% | −8 dB (rises **+6 dB**) |
| 10s | 60% | −4.4 dB (rises **+3.6 dB**) |
| 15s | 80% | −1.9 dB (rises **+2.5 dB**) |
| 20s | 100% | 0 dB (rises **+1.9 dB**) |

**Each successive 5-second window gains less perceived loudness.** A linear amplitude curve sounds "fast at the start, slowing toward the peak" — the opposite of natural approach.

### The fix: dB-linear (exponential amplitude)

`v(t) = 0.2 · 5^(t/20)` keeps the **dB step constant per second**:

| Time | Exponential amplitude | dB |
|---|---|---|
| 0s | 20% | −14 dB |
| 5s | 30% | −10.5 dB (rises **+3.5 dB**) |
| 10s | 45% | −7 dB (rises **+3.5 dB**) |
| 15s | 67% | −3.5 dB (rises **+3.5 dB**) |
| 20s | 100% | 0 dB (rises **+3.5 dB**) |

Every 5s window gains exactly +3.5 dB — perceptually uniform.

### Measured impact (v3 vs v2 of this repo)

Both files have identical sustain and drop sections. Only the rise differs:

| Metric | v2 (linear) | v3 (exponential) |
|---|---|---|
| LRA (loudness range) | 9.2 LU | **11.6 LU** |
| LRA low | −21.1 LUFS | **−23.4 LUFS** (more "distant" start) |
| Peak | −5.2 dBFS | −5.2 dBFS (climax unchanged) |

**Decision: exponential rise. Formula: `v(t) = 0.2 · 5^(t/20)`.**

---

## 5. Why 20% start (not 0%, not 50%)?

### Why not 0%?

A true silent start (0%) followed by a rising tone has a **perceptual artifact**: the brain registers "nothing → something" as a discrete event, not a continuum. The ringtone feels like it "snapped on" rather than "approached."

20% (≈ −14 dB) is **just above the listening threshold in a typical room** but well below conversational levels. Listeners perceive it as "already happening, just far away."

### Why not 50%?

50% defeats the "rise" — there's nowhere to go. The climax-to-start ratio collapses to 6 dB, which is barely a doubling. The drama is lost.

### Why 20% specifically?

20% = −14 dB → 0 dB gives a **14 dB rise** — perceptually about **3× louder** at the climax versus the start. That's enough to feel like an arrival, not so much that the start is inaudible.

**Decision: start at 20%.** Adjust to 15% for "more distant" feel, 25% for "closer start."

---

## 6. Why 7-second sustain?

| Sustain duration | Verdict |
|---|---|
| 3s | "barely registers as a peak, feels cut off" |
| 5s | "minimum acceptable, but no breathing room" |
| **7s** | **"climax has weight, you actually hear the drumbeat pattern"** |
| 12s | "starts to feel monotonous; loses urgency" |

For percussive content (drums, bells), 7s allows ~3–5 full beat cycles at climax volume. For melodic content, it lets a full musical phrase land.

**Decision: 7s, with a hard floor of 5s.**

---

## 7. Why linear drop (not exponential)?

Counter-intuitive but correct. Look at the listener's experience:

- **Exponential drop** (`v = 5^(−(t−27)/3)`) → drops slowly at first, then suddenly silent. Feels like the audio "fell off a cliff."
- **Linear drop** (`v = 1 − (t−27)/3`) → drops fast initially, then trails off. Feels like the source "moved away."

The user's spec was "**sharp but smooth descent**" — that's linear amplitude:

| Time | Linear amp | dB |
|---|---|---|
| 27.0s | 100% | 0 dB |
| 27.5s | 83% | −1.6 dB |
| 28.0s | 67% | −3.5 dB (drops **−3.5 dB**) |
| 28.5s | 50% | −6 dB (drops **−2.5 dB**) |
| 29.0s | 33% | −9.5 dB (drops **−3.5 dB**) |
| 29.5s | 17% | −15.6 dB (drops **−6.1 dB**) |
| 30.0s | 0% | −∞ (drops **−∞**) |

The accelerating dB descent in the final second creates the "sharp" exit, while the gradual amplitude fall in the first 1.5 seconds feels "smooth." Linear is the right shape for departure.

**Decision: linear drop. Formula: `v(t) = max(0, 1 − (t−27)/3)`.**

---

## 8. Why 3-second drop (not 5s, not 1s)?

| Drop duration | Verdict |
|---|---|
| 1s | "abrupt, feels like the speaker was unplugged" |
| 2s | "still too sudden for relaxed listening" |
| **3s** | **"sharp enough to feel intentional, smooth enough to feel deliberate"** |
| 5s | "drags on; loses the 'sharp' quality" |
| 9s (symmetric to 9s rise) | "way too long; sounds like the audio is hesitating to leave" |

3s is the **minimum perceptual length** for an "intentional" decay. Below that it reads as accident; above it reads as indecision.

**Decision: 3s.**

---

## 9. Verification standard

A correctly-forged ringtone must satisfy:

| Metric | Target | Tool |
|---|---|---|
| Duration | exactly 30.000s | `ffprobe -show_entries format=duration` |
| True peak | ≤ −1 dBFS (no clipping) | `ffmpeg ... -af ebur128=peak=true` |
| Integrated loudness | −16 to −12 LUFS | `ffmpeg ... -af ebur128` |
| LRA (dynamic range) | 8–14 LU | (above) |
| RMS at t=0s | < −25 dB | `ffmpeg -ss 0 -t 0.5 ... -af astats` |
| RMS at t=15s | within 6 dB of peak | (above) |
| RMS at t=29.7s | < −40 dB | (above) |

`scripts/verify-ringtone.sh` automates this checklist.

---

## 10. The complete formula

```
                          ┌── exponential ──┬─ flat ─┬── linear ──┐
v(t) = if t < 20:  0.2 · 5^(t/20)
       elif t < 27: 1.0
       else:        max(0, 1 − (t−27)/3)
                          └─────────────────┴────────┴────────────┘
                              0─20s            20-27s    27-30s
```

Encoded as a single ffmpeg filter expression:

```
volume='if(lt(t,20), 0.2*pow(5,t/20), if(lt(t,27), 1, max(0, 1-(t-27)/3)))':eval=frame
```

`:eval=frame` is critical — it tells ffmpeg to recompute the volume on every audio frame, not once at filter-init time.

---

## 11. Adapting the recipe

The formula is a **starting point**, not a dogma. Tune for content:

| Source type | Adjustment |
|---|---|
| Soft melodic (piano, strings) | Start at 30% (less distant); rise to 18s; sustain 8s; drop 4s |
| Fast electronic (EDM drop) | Start at 15% (more distant); rise 22s; sustain 5s; drop 3s |
| Voice / spoken | Drop the rise; just trim and apply 1s fade-in + 2s fade-out |
| Percussion (this case) | Use the recipe as-is |

Always re-verify with `verify-ringtone.sh` after tuning.

---

## References

- [ITU-R BS.1770-4](https://www.itu.int/rec/R-REC-BS.1770) — loudness measurement standard (LUFS)
- [EBU R128](https://tech.ebu.ch/publications/r128) — loudness normalization recommendation
- [ffmpeg volume filter docs](https://ffmpeg.org/ffmpeg-filters.html#volume) — `eval=frame` semantics
- Fletcher–Munson curves — equal-loudness contours, rationale for log perception
