"""Back-compat re-export shim.

The implementation lives in :mod:`cloudagent_ext.utils.at_file_completer`.
This shim preserves the legacy ``src.repl.at_file_completer`` import
path for callers that still reach it (the prompt_toolkit REPL bootstrap,
the historical ``tests/input/test_at_file_completer.py``, and a few
``cloudagent_ext/repl/*`` modules that take a lazy import to avoid a hard
dependency on prompt_toolkit at module-import time).

Direct imports of the public + private-helper names are listed
explicitly so test collection fails loudly if a name is renamed at the
new location — a star-import would silently miss tests that reach into
``_filter_candidates`` / ``_is_path_like_token`` / etc.
"""

from __future__ import annotations

from cloudagent_ext.utils.at_file_completer import (
    AtFileCompleter,  # primary class (Completer subclass)
    # Private helpers reached into by tests/input/test_at_file_completer.py:
    _build_path_bitmap,  # WI-3.1
    _filter_candidates,
    _is_path_like_token,
    _path_completions,
    _subsequence_score,
)

__all__ = [
    'AtFileCompleter',
    '_build_path_bitmap',
    '_filter_candidates',
    '_is_path_like_token',
    '_path_completions',
    '_subsequence_score',
]
