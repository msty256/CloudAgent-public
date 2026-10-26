"""Facade — bridge/session_runner.py has been moved to extensions/ports/bridge/.

The full session child-CLI spawner (Phase 4) now lives in
:mod:`extensions.ports.bridge.session_runner`. This module re-exports
the public surface so existing ``from src.bridge.session_runner import ...``
callers keep working without modification.
"""

from extensions.ports.bridge.session_runner import *  # noqa: F401,F403
