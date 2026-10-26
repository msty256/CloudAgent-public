"""Facade — bridge/repl_bridge.py has been moved to extensions/ports/bridge/.

The full ReplBridge implementation (Phase 6 MVP slice) now lives in
:mod:`extensions.ports.bridge.repl_bridge`. This module re-exports
the public surface so existing ``from src.bridge.repl_bridge import ...``
callers keep working without modification.
"""

from extensions.ports.bridge.repl_bridge import *  # noqa: F401,F403
