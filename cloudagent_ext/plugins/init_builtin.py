"""initBuiltinPlugins analog (PLUGINS-1) — +.
Idempotent: registration replaces by name, so calling twice is harmless.
"""

from __future__ import annotations

from .karpathy_guidelines import register_karpathy_guidelines_plugin


def init_builtin_plugins() -> None:
    register_karpathy_guidelines_plugin()
