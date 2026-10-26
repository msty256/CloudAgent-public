#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""OAuth service-layer helpers used by the bridge HTTP client.
 that the bridge subsystem
needs:
* ``get_organization_uuid()`` — read the org UUID for HTTP headers
  (``x-organization-uuid``).
The file is 589 lines and includes the full OAuth login flow, token
exchange, refresh wiring, and analytics. This Python port is a thin
shim over ``src.auth.claude_ai.get_oauth_account_info()``; the full
flow ports in Phase 10.
"""

from __future__ import annotations

from cloudagent_ext.auth.claude_ai import get_oauth_account_info


async def get_organization_uuid() -> str | None:
    """Return the current organization UUID, or ``None``.
    by, ``getBridgeSession``, ``archiveBridgeSession``,
    and ``updateBridgeSessionTitle`` to build the ``x-organization-uuid``
    header. Returns ``None`` when no account is configured (matches 
    ``undefined`` for the unconfigured path).
    Async because the counterpart awaits the keychain read; the
    Python env-var path is synchronous but the signature is kept async
    to make swapping to a real keychain in Phase 10 a non-breaking
    change.
    """
    info = get_oauth_account_info()
    if info is None:
        return None
    return info.organization_uuid


__all__ = ["get_organization_uuid"]
