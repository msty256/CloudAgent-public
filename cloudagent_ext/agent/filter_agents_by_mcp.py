#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Filter agents by their declared ``required_mcp_servers``.
.
Built-in agents are never dropped — they're trusted regardless of MCP
availability.
"""

from __future__ import annotations

from collections.abc import Iterable

from cloudagent_ext.agent.agent_definitions import AgentDefinition, is_built_in_agent


def has_required_mcp_servers(
    agent: AgentDefinition,
    available_servers: Iterable[str],
) -> bool:
    """Return True iff every required pattern matches an available server.
    Matching is case-insensitive substring (same as the reference): the
    pattern ``slack`` matches the server name ``MySlackServer``. Empty
    requirements pass through.
    """
    if not agent.required_mcp_servers:
        return True
    available_lower = [s.lower() for s in available_servers]
    return all(any(pattern.lower() in server for server in available_lower) for pattern in agent.required_mcp_servers)


def filter_agents_by_mcp_requirements(
    agents: Iterable[AgentDefinition],
    available_servers: Iterable[str],
) -> list[AgentDefinition]:
    """Drop agents whose required MCP servers aren't available.
    Built-ins are exempt: they're not allowed to declare requirements and
    must always be reachable.
    """
    available_list = list(available_servers)
    return [agent for agent in agents if is_built_in_agent(agent) or has_required_mcp_servers(agent, available_list)]
