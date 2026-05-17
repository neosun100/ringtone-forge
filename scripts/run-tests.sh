#!/usr/bin/env bash
# run-tests.sh — local CI runner for ringtone-forge.
#
# Usage:
#   ./scripts/run-tests.sh             # full suite (unit + integration + regression + e2e)
#   ./scripts/run-tests.sh --fast      # unit tests only, skip slow/network markers
#   ./scripts/run-tests.sh --ci        # CI mode: full suite, no colour, fail-fast on first error
#
# The runner uses pytest markers to skip tests that require unavailable
# capabilities (no torch / no MPS / no real audio). Run --doctor first
# if you want to know which capabilities are detected.

set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
cd "$PROJECT_ROOT"

MODE="full"
EXTRA_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --fast)  MODE="fast" ;;
        --ci)    MODE="ci"; EXTRA_ARGS+=(--color=no -x) ;;
        --help|-h)
            sed -n '2,11p' "$0" | sed 's/^# //'; exit 0 ;;
        *)
            EXTRA_ARGS+=("$arg") ;;
    esac
done

bold()    { printf '\033[1m%s\033[0m\n' "$*"; }
ok()      { printf '\033[32m%s\033[0m\n' "$*"; }
warn()    { printf '\033[33m%s\033[0m\n' "$*"; }
section() { printf '\n\033[1m\033[34m──────  %s  ──────\033[0m\n' "$*"; }

if ! command -v uv >/dev/null 2>&1; then
    echo "run-tests.sh: uv not found in PATH" >&2
    exit 69
fi

# Quick sanity probe — surface env capabilities once.
section "Environment doctor"
uv run ringtone-forge --doctor || true

if [[ "$MODE" == "fast" ]]; then
    section "Unit tests (fast mode)"
    uv run pytest tests/unit/ -m "not slow and not network" "${EXTRA_ARGS[@]}"
    ok "✓ Fast suite passed."
    exit 0
fi

# Full suite: layer by layer, fail-fast within each layer
overall_failures=0

section "1. Unit tests"
if uv run pytest tests/unit/ "${EXTRA_ARGS[@]}"; then
    ok "✓ Unit tests passed."
else
    warn "✗ Unit tests had failures."
    overall_failures=$((overall_failures + 1))
fi

section "2. Integration tests"
if uv run pytest tests/integration/ "${EXTRA_ARGS[@]}"; then
    ok "✓ Integration tests passed."
else
    warn "✗ Integration tests had failures."
    overall_failures=$((overall_failures + 1))
fi

section "3. Regression tests (5 reference songs)"
if uv run pytest tests/regression/ "${EXTRA_ARGS[@]}"; then
    ok "✓ Regression tests passed (5-song picks unchanged)."
else
    warn "✗ Regression tests had failures — check whether the new picks are intentional."
    overall_failures=$((overall_failures + 1))
fi

section "4. End-to-end tests"
if uv run pytest tests/e2e/ "${EXTRA_ARGS[@]}"; then
    ok "✓ E2E tests passed."
else
    warn "✗ E2E tests had failures."
    overall_failures=$((overall_failures + 1))
fi

echo
if [[ "$overall_failures" -eq 0 ]]; then
    ok "═══════════════════════════════════════════════════════════════"
    ok "  All test layers passed. Safe to commit + push."
    ok "═══════════════════════════════════════════════════════════════"
    exit 0
else
    warn "═══════════════════════════════════════════════════════════════"
    warn "  $overall_failures layer(s) had failures. Review above before pushing."
    warn "═══════════════════════════════════════════════════════════════"
    exit "$overall_failures"
fi
