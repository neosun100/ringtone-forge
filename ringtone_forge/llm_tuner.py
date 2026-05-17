"""
LLM tuning module — translate user preferences and audio analysis into
envelope parameters via a large language model.

Why this module exists
======================

ringtone-forge v2.3 had a Skill (~/.kiro/skills/ringtone-forge/SKILL.md)
that taught *external* LLM agents (Kiro / Claude Code / Cursor) how to
call the CLI. v2.4 closes the loop: an *internal* LLM call inside the
tool itself, so users without an Agent platform can still get the LLM
benefits via ``--tune`` and ``--agent`` flags.

The LLM does three things in this module:

1. **Translate preference language → parameters.**
   "开头再轻一点" / "渐入慢一倍" / "更带感" → concrete numbers for
   rise / sustain / drop / start_amp.

2. **Pick the best chorus candidate.**
   When the stems analyzer returns top-K candidates, the LLM reads
   each one's feature explanation and picks the most "chorus-like"
   based on song structure intuition.

3. **Diagnose verify failures and propose fixes.**
   When the 7-point quality bar fails, the LLM reads which checks
   failed and proposes parameter adjustments for retry.

Three backends, one interface
==============================

- **anthropic** — Anthropic API (Claude Sonnet 4.5 by default).
  Best quality, requires ``ANTHROPIC_API_KEY``.
- **openai** — OpenAI-compatible API (GPT-4o-mini by default).
  Cheapest at small request volume, requires ``OPENAI_API_KEY``.
- **ollama** — Local Ollama server (llama3.2 by default).
  Zero cost, runs locally, requires ``ollama serve`` running.

The module auto-selects in this priority order:
``anthropic > openai > ollama > mock``. Pass ``backend="..."`` to force a
specific one. ``mock`` is for tests — returns deterministic dummy outputs
without any network call.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

LLMBackend = Literal["auto", "anthropic", "openai", "ollama", "mock"]

# Default models per backend. Override via env or constructor.
_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5-20250929",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.2",
}


# ---------------------------------------------------------------------------
# Public dataclass for tuning output
# ---------------------------------------------------------------------------

@dataclass
class TuningResult:
    """Output of a single LLM call.

    Attributes
    ----------
    rise, sustain, drop, start_amp, duration, preset:
        Suggested values; any of them may be ``None`` if the LLM didn't
        propose a change (caller falls back to existing default).
    explanation:
        One- or two-sentence justification, in the user's language.
    backend:
        Which backend produced this result; useful for debugging.
    raw_response:
        The full model response, for logging.
    """

    rise: Optional[float] = None
    sustain: Optional[float] = None
    drop: Optional[float] = None
    start_amp: Optional[float] = None
    duration: Optional[float] = None
    preset: Optional[str] = None
    explanation: str = ""
    backend: str = ""
    raw_response: str = ""

    def to_envelope_kwargs(self) -> dict:
        """Filter out Nones — ready to pass to ``resolve_envelope_params``."""
        kwargs = {}
        if self.rise is not None:      kwargs["user_rise"] = self.rise
        if self.sustain is not None:   kwargs["user_sustain"] = self.sustain
        if self.drop is not None:      kwargs["user_drop"] = self.drop
        if self.start_amp is not None: kwargs["user_start_amp"] = self.start_amp
        if self.duration is not None:  kwargs["user_duration"] = self.duration
        if self.preset is not None:    kwargs["user_preset"] = self.preset
        return kwargs


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def detect_available_backends() -> list[str]:
    """Probe environment to find which LLM backends can be used."""
    available = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # noqa: F401
            available.append("anthropic")
        except ImportError:
            pass
    if os.environ.get("OPENAI_API_KEY"):
        try:
            import openai  # noqa: F401
            available.append("openai")
        except ImportError:
            pass
    if _ollama_running():
        available.append("ollama")
    available.append("mock")  # always available as a fallback for tests
    return available


def _ollama_running() -> bool:
    """Quick probe to see if a local Ollama server is listening."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=0.5):
            return True
    except Exception:
        return False


def _resolve_backend(requested: LLMBackend = "auto") -> str:
    if requested != "auto":
        return requested
    available = detect_available_backends()
    # Priority: best LLM available
    for choice in ("anthropic", "openai", "ollama", "mock"):
        if choice in available:
            return choice
    return "mock"


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an expert audio engineer helping tune a 30-second
ringtone forge tool. The tool extracts a 30-second highlight from any song
using a three-stage volume envelope: exponential rise → flat sustain → linear drop.

Three presets exist as starting points:
  - vocal      : 5s rise + 22s sustain + 3s drop, start_amp=0.50  (pop songs with dense choruses)
  - melodic    : 12s rise + 15s sustain + 3s drop, start_amp=0.30 (electronic/instrumental)
  - percussive : 20s rise + 7s sustain + 3s drop, start_amp=0.20  (drum loops / "approaching from afar")

The user gives you either:
  - a natural-language preference  ("开头再轻一点", "渐入慢一倍", "更带感")
  - a verify report showing failed checks  ("RMS@0s = -16dB but should be < -25dB")
  - the choice between top-K candidate windows

Your job: respond with **JSON only** (no prose, no markdown, no code fences),
giving the parameter overrides that should be applied. Use this schema:

{
  "rise": <float seconds or null>,
  "sustain": <float seconds or null>,
  "drop": <float seconds or null>,
  "start_amp": <float in (0,1] or null>,
  "duration": <float seconds or null>,
  "preset": <"vocal"|"melodic"|"percussive"|null>,
  "explanation": "<1-2 sentences in the user's language explaining what you changed>"
}

Use null for any field you do not want to change. Be conservative — change
only what's needed. Respect physical constraints: rise + sustain + drop
should sum to duration (default 30s)."""


def _build_tune_prompt(
    audio_type: str,
    user_preference: str,
    duration: float = 30.0,
    classification_features: Optional[dict] = None,
) -> str:
    parts = [
        f"Audio type: {audio_type} (current default preset)",
        f"Total ringtone duration: {duration:.1f}s",
    ]
    if classification_features:
        feat_str = ", ".join(f"{k}={v}" for k, v in classification_features.items())
        parts.append(f"Classifier features: {feat_str}")
    parts.append("")
    parts.append(f"User preference: {user_preference!r}")
    parts.append("")
    parts.append("Respond with JSON only:")
    return "\n".join(parts)


def _build_diagnose_prompt(
    failed_checks: list[dict],
    current_params: dict,
) -> str:
    lines = ["The following verify checks failed:"]
    for c in failed_checks:
        lines.append(f"  - {c.get('name', '?')}: {c.get('actual', '?')}")
    lines.append("")
    lines.append("Current envelope parameters:")
    for k, v in current_params.items():
        lines.append(f"  {k} = {v}")
    lines.append("")
    lines.append("Suggest parameter adjustments to fix the failures. Respond with JSON only:")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Backend-specific call wrappers
# ---------------------------------------------------------------------------

def _call_anthropic(prompt: str, model: Optional[str] = None) -> str:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model or _DEFAULT_MODELS["anthropic"],
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _call_openai(prompt: str, model: Optional[str] = None) -> str:
    from openai import OpenAI
    client = OpenAI()
    resp = client.chat.completions.create(
        model=model or _DEFAULT_MODELS["openai"],
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
    )
    return resp.choices[0].message.content or ""


def _call_ollama(prompt: str, model: Optional[str] = None) -> str:
    import urllib.request
    body = json.dumps({
        "model": model or _DEFAULT_MODELS["ollama"],
        "system": _SYSTEM_PROMPT,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    return data.get("response", "")


def _call_mock(prompt: str, model: Optional[str] = None) -> str:
    """Deterministic fake response for tests.

    Inspects the prompt for simple keywords and returns a plausible JSON.
    Real LLMs do much better — this exists only so unit tests don't need
    network access.
    """
    p = prompt.lower()
    if any(k in p for k in ["渐入", "开头", "轻", "rise", "lighter", "slow", "softer", "quiet"]):
        return json.dumps({
            "rise": 10.0, "sustain": None, "drop": None,
            "start_amp": 0.30, "duration": None, "preset": None,
            "explanation": "[mock] increased rise to 10s and lowered start_amp to 0.30",
        }, ensure_ascii=False)
    if any(k in p for k in ["loud", "炸", "带感", "punchy", "energetic"]):
        return json.dumps({
            "rise": 3.0, "sustain": 24.0, "drop": None,
            "start_amp": 0.6, "duration": None, "preset": None,
            "explanation": "[mock] shortened rise, more sustain, louder start",
        }, ensure_ascii=False)
    return json.dumps({
        "rise": None, "sustain": None, "drop": None,
        "start_amp": None, "duration": None, "preset": None,
        "explanation": "[mock] no changes suggested",
    }, ensure_ascii=False)


_BACKENDS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "ollama": _call_ollama,
    "mock": _call_mock,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _parse_response(raw: str) -> dict:
    """Extract a JSON object from the model response.

    Tolerates code fences and surrounding prose, since not every model
    obeys "JSON only".
    """
    # Try fenced code block first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Fall back to first {...} block
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"could not extract JSON from response: {raw!r}")


def tune_from_preference(
    audio_type: str,
    user_preference: str,
    duration: float = 30.0,
    classification_features: Optional[dict] = None,
    backend: LLMBackend = "auto",
    model: Optional[str] = None,
) -> TuningResult:
    """Translate a natural-language preference into envelope parameters.

    Parameters
    ----------
    audio_type:
        ``vocal`` / ``melodic`` / ``percussive`` from the classifier.
    user_preference:
        Free-form text such as "渐入再慢一倍" or "make the start quieter".
    duration:
        Total ringtone length in seconds.
    classification_features:
        Optional dict of ``mfcc_variance``, ``chroma_std``, etc, for the
        LLM to consider.
    backend:
        ``auto`` picks the best available, or force ``anthropic`` /
        ``openai`` / ``ollama`` / ``mock``.
    model:
        Override the default model name for the chosen backend.
    """
    chosen = _resolve_backend(backend)
    prompt = _build_tune_prompt(audio_type, user_preference, duration, classification_features)
    raw = _BACKENDS[chosen](prompt, model)
    try:
        data = _parse_response(raw)
    except (ValueError, json.JSONDecodeError):
        return TuningResult(explanation=f"[{chosen}] failed to parse LLM response", backend=chosen, raw_response=raw)
    return TuningResult(
        rise=data.get("rise"),
        sustain=data.get("sustain"),
        drop=data.get("drop"),
        start_amp=data.get("start_amp"),
        duration=data.get("duration"),
        preset=data.get("preset"),
        explanation=data.get("explanation", ""),
        backend=chosen,
        raw_response=raw,
    )


def diagnose_verify_failure(
    failed_checks: list[dict],
    current_params: dict,
    backend: LLMBackend = "auto",
    model: Optional[str] = None,
) -> TuningResult:
    """Read a verify report's failures and propose fixes.

    Parameters
    ----------
    failed_checks:
        List of dicts with at least ``name`` and ``actual`` keys, e.g.
        ``[{"name": "RMS at t=0s < -25 dB", "actual": "-18.2 dB"}]``.
    current_params:
        Dict of the parameters used in the failing run.
    """
    chosen = _resolve_backend(backend)
    prompt = _build_diagnose_prompt(failed_checks, current_params)
    raw = _BACKENDS[chosen](prompt, model)
    try:
        data = _parse_response(raw)
    except (ValueError, json.JSONDecodeError):
        return TuningResult(explanation=f"[{chosen}] failed to parse LLM response", backend=chosen, raw_response=raw)
    return TuningResult(
        rise=data.get("rise"),
        sustain=data.get("sustain"),
        drop=data.get("drop"),
        start_amp=data.get("start_amp"),
        duration=data.get("duration"),
        preset=data.get("preset"),
        explanation=data.get("explanation", ""),
        backend=chosen,
        raw_response=raw,
    )


__all__ = [
    "LLMBackend",
    "TuningResult",
    "detect_available_backends",
    "tune_from_preference",
    "diagnose_verify_failure",
]
