"""Facade — transports/hybrid_transport.py has been moved to extensions/ports/transports/.

The full hybrid transport (WebSocket reads + HTTP POST writes) for the v1
bridge path now lives in :mod:`extensions.ports.transports.hybrid_v1`
(renamed from ``hybrid_transport.py`` to disambiguate from the v2
transport). This module re-exports the public surface so existing
``from src.transports.hybrid_transport import ...`` callers keep working.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__``.
"""

import extensions.ports.transports.hybrid_v1 as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)

# Keep private URL conversion helpers reachable through the historical path.
import sys

sys.modules[__name__] = _mod
