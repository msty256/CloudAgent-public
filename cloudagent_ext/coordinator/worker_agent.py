#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""WORKER agent definition — Chunk G / WI-8.5.
coordinator mode are spread from ``GENERAL_PURPOSE_AGENT`` with two
edits:
* ``agent_type`` becomes ``"worker"`` so the coordinator system
  prompt's ``subagent_type: "worker"`` calls resolve correctly.
* ``when_to_use`` is rephrased for the coordinator-mode role.
Workers do NOT lose tools at the agent-definition level — the
``INTERNAL_WORKER_TOOLS`` filter (``coordinator/mode.py``) handles
that at tool-set construction time. Keeping the filter at the
mode-level (rather than baking it into the agent definition) means
the same WORKER definition can be reused for non-coordinator paths
in the future without re-editing.
``get_coordinator_agents()`` returns the canonical agent list for
coordinator-mode sessions.
Originally lived at
``src/coordinator/worker_agent.py``; moved to ``cloudagent_ext/`` during the single-layering
refactor. The ``src/`` compatibility facade was removed along with it,
so import the ``cloudagent_ext`` path directly.
"""

from __future__ import annotations

from dataclasses import replace

from cloudagent_ext.agent.agent_definitions import (
    EXPLORE_AGENT,
    GENERAL_PURPOSE_AGENT,
    PLAN_AGENT,
    AgentDefinition,
)


# Spread GENERAL_PURPOSE → tweak agent_type + when_to_use. Mirrors
#.
WORKER_AGENT: AgentDefinition = replace(
    GENERAL_PURPOSE_AGENT,
    agent_type="worker",
    when_to_use=(
        "Worker agent for coordinator mode. Executes tasks autonomously — research, implementation, or verification."
    ),
)


def get_coordinator_agents() -> list[AgentDefinition]:
    """Return the canonical agent list for coordinator-mode sessions.
    EXPLORE, PLAN]``. ``WORKER`` first so the coordinator system
    prompt's ``subagent_type: "worker"`` resolves to the right
    definition; ``GENERAL_PURPOSE`` / ``EXPLORE`` / ``PLAN`` follow
    so the legacy spawning paths still work in coordinator mode.
    """
    return [WORKER_AGENT, GENERAL_PURPOSE_AGENT, EXPLORE_AGENT, PLAN_AGENT]


__all__ = [
    "WORKER_AGENT",
    "get_coordinator_agents",
]
