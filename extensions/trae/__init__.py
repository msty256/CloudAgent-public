# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Trae IDE integration (Layer 2).

Two complementary sub-features:
  * ``mcp_bridge`` — MCP reverse bridge: Trae IDE calls cloudagent via MCP
  * ``acp_cli_adapter`` — wraps ByteDance's open-source trae-cli as a pseudo ACP server

The two mirror each other: the trae-cli process started by the adapter
can mount the MCP server exposed by the bridge, forming a two-way loop.
See ``docs/feature_plan/06-ccb-benchmark/f-66-acp-protocol.md``.

Fully decoupled in Layer 2 — deleting this directory rolls back cleanly
without affecting ``src/`` or ``cloudagent_ext/``.
"""

from __future__ import annotations

__all__ = ["mcp_bridge", "acp_cli_adapter"]
