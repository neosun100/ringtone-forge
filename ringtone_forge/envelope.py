"""
Volume envelope — genre-adaptive presets and ffmpeg integration.

The v1.0 recipe (20s exponential rise + 7s sustain + 3s linear drop) was
tuned on a drum loop. It works beautifully for percussive content but is
*wrong* for vocal pop, where the chorus is dense and the listener wants to
arrive at the climax fast — a 20-second build-up wastes two-thirds of the
ringtone on warm-up.

This module exposes three presets, one per ``audio_type`` returned by the
classifier:

==========  ===========  =======  ====  ===========================
preset      rise         sustain  drop  rationale
==========  ===========  =======  ====  ===========================
vocal       5s exp       22s      3s    chorus is dense, get there fast
melodic     12s exp      15s      3s    medium build, balanced sections
percussive  20s exp      7s       3s    classic v1.0, "approaching from afar"
==========  ===========  =======  ====  ===========================

Every preset uses an exponential rise (dB-linear, equal-loudness perceived
ramp) and a linear drop (front-loaded amplitude descent = "sharp but smooth"
exit). Only the time allocation differs — keeping the qualitative character
consistent across genres.

The exponential formula generalises to::

    v(t) = start_amp * (1 / start_amp) ** (t / rise_seconds)

so::

    v(0)            = start_amp
    v(rise_seconds) = 1.0

and the dB step per second is constant (the ear's natural ramp).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PresetName = Literal["vocal", "melodic", "percussive"]


@dataclass(frozen=True)
class EnvelopePreset:
    """Three-stage envelope spec.

    All durations are in seconds and must add to ``total_seconds`` (defaults
    to 30).

    Attributes
    ----------
    name:
        Human-readable preset name.
    start_amp:
        Volume at t=0, in linear amplitude. 0.2 = ~−14 dB ("quite distant"),
        0.5 = −6 dB ("close already").
    rise_seconds:
        Length of the exponential rise. The amplitude reaches 1.0 at
        t = ``rise_seconds``.
    sustain_seconds:
        Length of the flat 100%-amplitude section.
    drop_seconds:
        Length of the linear drop from 100% to 0%.
    """

    name: PresetName
    start_amp: float
    rise_seconds: float
    sustain_seconds: float
    drop_seconds: float

    @property
    def total_seconds(self) -> float:
        return self.rise_seconds + self.sustain_seconds + self.drop_seconds

    @property
    def sustain_end(self) -> float:
        return self.rise_seconds + self.sustain_seconds


PRESETS: dict[PresetName, EnvelopePreset] = {
    "vocal": EnvelopePreset(
        name="vocal",
        start_amp=0.50,
        rise_seconds=5.0,
        sustain_seconds=22.0,
        drop_seconds=3.0,
    ),
    "melodic": EnvelopePreset(
        name="melodic",
        start_amp=0.30,
        rise_seconds=12.0,
        sustain_seconds=15.0,
        drop_seconds=3.0,
    ),
    "percussive": EnvelopePreset(
        name="percussive",
        start_amp=0.20,
        rise_seconds=20.0,
        sustain_seconds=7.0,
        drop_seconds=3.0,
    ),
}


def get_preset(
    name: PresetName | str,
    *,
    rise: float | None = None,
    sustain: float | None = None,
    drop: float | None = None,
    start_amp: float | None = None,
    duration: float | None = None,
) -> EnvelopePreset:
    """Look up a preset by name, optionally overriding any parameter.

    All keyword args are optional. Any value supplied replaces the preset
    default. If ``duration`` is given, the rise/sustain/drop are scaled
    proportionally so they still sum to ``duration``.

    Examples
    --------
    >>> get_preset("vocal")                                   # standard 5+22+3
    >>> get_preset("vocal", rise=10)                          # 10+17+3 (sustain shrinks)
    >>> get_preset("vocal", rise=8, sustain=19, drop=3)       # full custom (must sum to 30)
    >>> get_preset("vocal", duration=15)                      # scaled down to 15s total
    """
    if name not in PRESETS:
        raise KeyError(
            f"Unknown envelope preset: {name!r}. Choose one of {list(PRESETS.keys())}."
        )
    base = PRESETS[name]

    # Apply duration scaling first if requested
    if duration is not None and duration > 0 and duration != base.total_seconds:
        scale = duration / base.total_seconds
        scaled_rise = base.rise_seconds * scale
        scaled_sustain = base.sustain_seconds * scale
        scaled_drop = base.drop_seconds * scale
    else:
        scaled_rise = base.rise_seconds
        scaled_sustain = base.sustain_seconds
        scaled_drop = base.drop_seconds

    # Apply explicit overrides on top of scaling
    final_rise = rise if rise is not None else scaled_rise
    final_sustain = sustain if sustain is not None else scaled_sustain
    final_drop = drop if drop is not None else scaled_drop
    final_start_amp = start_amp if start_amp is not None else base.start_amp

    # Sanity check — non-negative durations
    if final_rise < 0 or final_sustain < 0 or final_drop < 0:
        raise ValueError(
            f"All durations must be ≥ 0; got rise={final_rise}, "
            f"sustain={final_sustain}, drop={final_drop}"
        )
    if not (0.0 < final_start_amp <= 1.0):
        raise ValueError(f"start_amp must be in (0, 1]; got {final_start_amp}")

    return EnvelopePreset(
        name=base.name,
        start_amp=final_start_amp,
        rise_seconds=final_rise,
        sustain_seconds=final_sustain,
        drop_seconds=final_drop,
    )


def resolve_envelope_params(
    audio_type: str,
    *,
    user_rise: float | None = None,
    user_sustain: float | None = None,
    user_drop: float | None = None,
    user_start_amp: float | None = None,
    user_duration: float | None = None,
    user_preset: str | None = None,
) -> EnvelopePreset:
    """Resolve the final envelope spec for a given run.

    Decision order (later overrides earlier):
      1. Pick a preset by ``audio_type`` (vocal/melodic/percussive)
      2. If ``user_preset`` is given, override the preset name
      3. Apply user-specified rise/sustain/drop/start_amp/duration on top

    This is the single entry point used by the CLI and by the LLM tuner.
    """
    preset_name = user_preset if user_preset else audio_type
    return get_preset(
        preset_name,
        rise=user_rise,
        sustain=user_sustain,
        drop=user_drop,
        start_amp=user_start_amp,
        duration=user_duration,
    )


def build_filter_expression(preset: EnvelopePreset) -> str:
    """Produce the ffmpeg ``volume`` filter expression for this preset.

    The expression has the form::

        if(lt(t, R), START * pow(1/START, t/R),
        if(lt(t, R+S), 1,
                       max(0, 1 - (t - (R+S)) / D)))

    where R, S, D are rise/sustain/drop durations and START is the starting
    amplitude.

    Returns
    -------
    str
        A complete ``-af "volume=..."`` argument body. Pass to ffmpeg with
        ``:eval=frame`` to ensure the volume is recomputed every frame.
    """
    R = preset.rise_seconds
    S = preset.sustain_seconds
    D = preset.drop_seconds
    A = preset.start_amp
    sustain_end = R + S
    growth_base = 1.0 / A  # reaches 1.0 when t == R

    return (
        f"volume='if(lt(t,{R}), {A}*pow({growth_base},t/{R}), "
        f"if(lt(t,{sustain_end}), 1, "
        f"max(0, 1-(t-{sustain_end})/{D})))':eval=frame,"
        # Brick-wall limiter — many modern pop sources are already mastered
        # past 0 dBFS. We pull sample peak down to about -1.4 dBFS so the
        # true-peak (inter-sample) peak stays under +1 dBFS even after AAC
        # encoding's own oversampling artefacts.
        f"alimiter=limit=0.78:level=disabled"
    )


def render_ascii(preset: EnvelopePreset, width: int = 60, height: int = 8) -> str:
    """ASCII visualisation of the envelope, useful for ``--analyze`` output."""
    lines = []
    lines.append(f"  envelope: {preset.name}  "
                 f"(rise {preset.rise_seconds:g}s · sustain {preset.sustain_seconds:g}s · drop {preset.drop_seconds:g}s)")
    grid = [[" "] * width for _ in range(height)]
    total = preset.total_seconds
    A = preset.start_amp
    R = preset.rise_seconds
    S = preset.sustain_seconds
    D = preset.drop_seconds

    for col in range(width):
        t = col * total / (width - 1)
        if t < R:
            v = A * (1.0 / A) ** (t / R)
        elif t < R + S:
            v = 1.0
        else:
            v = max(0.0, 1.0 - (t - (R + S)) / D)
        row = (height - 1) - int(round(v * (height - 1)))
        row = max(0, min(height - 1, row))
        grid[row][col] = "█"

    for r, row in enumerate(grid):
        amp = 1.0 - r / (height - 1)
        prefix = f"  {int(amp*100):3d}% │"
        lines.append(prefix + "".join(row))
    lines.append("        └" + "─" * width)
    lines.append(f"         0s{' ' * (width // 2 - 4)}{int(total/2)}s{' ' * (width // 2 - 4)}{int(total)}s")
    return "\n".join(lines)
