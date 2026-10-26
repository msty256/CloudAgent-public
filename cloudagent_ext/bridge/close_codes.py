#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""WebSocket close codes used by the CCR bridge layer.
 and
.
Single source of truth so consumers (Phase 3 `replBridgeTransport`,
Phase 4 `SessionsWebSocket`, Phase 1 `directConnectManager`) do not
re-define these magic numbers.
Originally lived at
``src/bridge/close_codes.py``; moved to ``cloudagent_ext/`` during the single-layering
refactor. The ``src/`` compatibility facade was removed along with it,
so import the ``cloudagent_ext`` path directly.
"""

from __future__ import annotations

from typing import Final

# ─── Server-initiated close codes the bridge transport synthesizes ─────

#: Worker epoch superseded — closes both transports; replBridge's poll
#: loop reconnects with a fresh epoch.
#:.
WS_CLOSE_EPOCH_MISMATCH: Final = 4090

#: CCRClient.initialize failed — closes both; poll loop will retry on
#: the next work dispatch.
#:.
WS_CLOSE_INIT_FAILURE: Final = 4091

#: SSE reconnect-budget exhausted — distinguishable from HTTP-status
#: closes so ws_closed telemetry can branch on it.
#:.
WS_CLOSE_RECONNECT_BUDGET_EXHAUSTED: Final = 4092

# ─── claude.ai → CCR session close codes (Phase 4 SessionsWebSocket) ───

#: Server says "you are not authorized for this session" — stop
#: reconnecting permanently.
#:.
WS_CLOSE_PERMANENT_UNAUTHORIZED: Final = 4003

#: Server says "session not found" — could be transient during
#: compaction; retry with limited linear backoff (max 3 attempts).
#:.
WS_CLOSE_SESSION_NOT_FOUND: Final = 4001


__all__ = [
    "WS_CLOSE_EPOCH_MISMATCH",
    "WS_CLOSE_INIT_FAILURE",
    "WS_CLOSE_PERMANENT_UNAUTHORIZED",
    "WS_CLOSE_RECONNECT_BUDGET_EXHAUSTED",
    "WS_CLOSE_SESSION_NOT_FOUND",
]
