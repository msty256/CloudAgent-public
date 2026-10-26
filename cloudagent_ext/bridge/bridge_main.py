"""Facade — bridge/bridge_main.py has been moved to extensions/ports/bridge/.

The full multi-session bridge daemon (Phase 8 MVP slice) now lives in
:mod:`extensions.ports.bridge.bridge_main`. This module re-exports
the public surface so existing ``from src.bridge.bridge_main import ...``
callers keep working without modification.
"""

from extensions.ports.bridge.bridge_main import *  # noqa: F401,F403
