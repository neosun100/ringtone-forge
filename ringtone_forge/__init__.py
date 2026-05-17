"""ringtone-forge: intelligent 30-second ringtone forge.

Public API:

    from ringtone_forge.classifier import classify
    from ringtone_forge.analyzer import analyze, align_to_beat
    from ringtone_forge.envelope import get_preset, build_filter_expression
    from ringtone_forge.verify import verify

The command-line entry point is ``ringtone_forge.cli.main``, registered as
the ``ringtone-forge`` console script via ``pyproject.toml``.
"""

__version__ = "2.2.0"

__all__ = [
    "__version__",
]
