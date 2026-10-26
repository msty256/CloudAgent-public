"""Facade — bridge/remote_bridge_core.py has been moved to extensions/ports/bridge/.

The full env-less Remote Control bridge core (Phase 5 MVP) now lives in
:mod:`extensions.ports.bridge.remote_bridge_core`. This module re-exports
the public surface so existing ``from src.bridge.remote_bridge_core import ...``
callers keep working without modification.

Uses ``globals().update()`` rather than ``from X import *`` to preserve
access to all public names regardless of ``__all__`` — the upstream
test suite references symbols (e.g. ``TokenRefreshScheduler``) that
are not in the module's ``__all__`` list.
"""

import extensions.ports.bridge.remote_bridge_core as _mod

# Re-export all public symbols (bypassing __all__ to match the original
# full-module behavior that tests/imports depend on).
_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
