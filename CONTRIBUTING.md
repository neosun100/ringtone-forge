# Contributing to ringtone-forge

Thanks for considering a contribution. This project is small but it's
real: real songs, real users, real measurements. Every change is welcome
provided it carries a test.

## Setup

```bash
git clone https://github.com/neosun100/ringtone-forge.git
cd ringtone-forge
uv sync --extra deep --extra dev      # full dev environment
uv run ringtone-forge --doctor        # confirm your environment is ready
```

## Running tests

The local CI runner is the source of truth:

```bash
./scripts/run-tests.sh                # full suite, layered (unit → integration → regression → e2e)
./scripts/run-tests.sh --fast         # unit tests only, no slow markers
./scripts/run-tests.sh --ci           # CI mode: no colour, fail-fast on first error
```

You can also call pytest directly with markers to target specific layers:

```bash
uv run pytest tests/unit/             # unit tests only
uv run pytest -m "regression"         # regression tests
uv run pytest -m "not slow"           # skip the demucs-heavy ones
uv run pytest -m "requires_mps"       # only Apple Silicon GPU paths
```

Tests automatically skip when their required capability is missing.
The matrix:

| Marker | What's needed |
|---|---|
| `requires_torch` | `[deep]` extras installed (PyTorch + demucs) |
| `requires_mps` | Apple Silicon Metal GPU |
| `requires_cuda` | NVIDIA GPU + CUDA |
| `requires_ffmpeg` | ffmpeg + ffprobe in PATH |
| `requires_real_audio` | The 5 reference songs in `samples/source/` |
| `slow` | Test takes >5s (demucs inference, etc.) |

## Test layers — what goes where

```
tests/
├── unit/         pure-Python tests; should run in <10s with no [deep] deps
├── integration/  CLI subprocess tests; need ffmpeg
├── regression/   pinned chorus picks for the 5 reference songs
└── e2e/          full pipeline → real ringtone file → verify
```

Add a new test:
- **Pure logic / math?** → `tests/unit/test_<module>.py`
- **CLI flag or subcommand?** → `tests/integration/test_cli.py`
- **New analyzer or change to picks?** → update `tests/regression/test_5_song_picks.py`
- **New end-to-end behaviour?** → add to `tests/e2e/`

## Updating regression baselines

When you intentionally change the analyzer (e.g. tune T2 weights or upgrade
demucs to a new version), regression tests will fail with messages like:

```
跳楼机: chorus start regressed — expected 144.5±2.0s, got 148.2s.
        Update PINNED_PICKS_V22 if the new pick is intentionally better.
```

To accept the new picks:

1. Listen to the new vs old ringtones (`samples/final-v22/` for old).
2. Confirm the new pick is musically as good or better.
3. Update `PINNED_PICKS_V22` in `tests/regression/test_5_song_picks.py`.
4. Note the change in CHANGELOG.md.

## Adding a new test song

```bash
cp my_song.mp3 samples/source/
# Generate the v2.2/2.3 baseline ringtone for visual comparison
uv run ringtone-forge samples/source/my_song.mp3 samples/final-v22/my_song_v22.m4a
# Add to regression pins:
#   tests/regression/test_5_song_picks.py
#   - EXPECTED_CLASSIFICATIONS
#   - PINNED_PICKS_V22
```

## Code style

- Follow existing patterns. We use type hints, docstrings, and Black-style
  formatting (no enforcer running yet, but consistency is appreciated).
- Functions documented with NumPy-style docstrings (see `stems_analyzer.py`).
- Keep modules independent — `classifier.py` doesn't depend on `analyzer.py`,
  `analyzer.py` doesn't depend on `stems_analyzer.py`.

## Commits

Conventional Commits style:
- `feat(scope): ...` — new capability
- `fix(scope): ...` — bug fix
- `test(scope): ...` — test additions / fixes
- `docs(scope): ...` — README / methodology changes
- `chore: ...` — version bumps, dependency updates

Always run the full test suite before pushing:
```bash
./scripts/run-tests.sh && git push
```

## Reporting bugs

If a song's ringtone sounds wrong:

1. Run `uv run ringtone-forge <song> --analyze --json` and attach the output.
2. Run `uv run ringtone-forge --doctor` and attach the output.
3. Note: which preset was chosen, what you expected the chorus to be, what
   the agent actually picked.

This information is enough to reproduce the issue on any of our three
validated environments (macOS MPS, Linux CUDA, Linux CPU).
