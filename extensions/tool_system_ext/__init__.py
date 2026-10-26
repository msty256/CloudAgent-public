# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""
Tool System Extension Layer

Provides optional tool bundle loading and per-agent tool configuration
without modifying upstream tool_system code.

Architecture:
    - bundles.py: Tool bundle definitions
    - registry_ext.py: Extended ToolRegistry with bundle support
    - agent_config.py: Agent tool configuration dataclass
"""

from __future__ import annotations


from .bundles import (
    TOOL_BUNDLES,
    MODE_BUNDLES,
    ALL_BUNDLE_NAMES,
    get_bundle_tools,
    get_all_bundle_tools,
)

from .registry_ext import ToolRegistryExt

from .agent_config import AgentToolConfig, ToolMode, load_tool_config

from .team_filter import (
    TEAM_ONLY_TOOL_NAMES,
    filter_team_only_tools,
    has_team_context,
)

__all__ = [
    "TOOL_BUNDLES",
    "MODE_BUNDLES",
    "ALL_BUNDLE_NAMES",
    "get_bundle_tools",
    "get_all_bundle_tools",
    "TEAM_ONLY_TOOL_NAMES",
    "ToolRegistryExt",
    "AgentToolConfig",
    "ToolMode",
    "filter_team_only_tools",
    "has_team_context",
    "load_tool_config",
]
