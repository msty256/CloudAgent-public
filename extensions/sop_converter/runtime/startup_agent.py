#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Build the main-loop AgentDefinition for ``--agent <bundle_dir>`` startup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from extensions.capabilities.agent_definition_protocol import AgentToolConstants
from ..adapters import DEFAULTS


def build_bundle_overview_agent_definition(
    agent: dict[str, Any],
    *,
    bundle_dir: Path,
) -> Any:
    """Turn a parsed overview agent dict into the REPL main-loop definition.

    Uses :meth:`AgentToolConstants.registered_proxy_base_tools` so the
    session starts with the SOP Overview routing set (Skill, ToolSearch,
    Agent, Read, TodoWrite, StructuredOutput).
    """
    name = str(agent.get("name") or "cloudagent-overview")
    raw_skills = agent.get("skills")
    skills: list[str] | None = None
    if isinstance(raw_skills, list):
        skills = [s for s in raw_skills if isinstance(s, str)]

    return DEFAULTS.agent_definition_factory(
        agent_type=name,
        when_to_use=str(agent.get("description") or ""),
        tools=AgentToolConstants.registered_proxy_base_tools(),
        skills=skills,
        source="dynamic",
        base_dir=str(bundle_dir.resolve()),
        model=agent.get("model") if isinstance(agent.get("model"), str) else None,
        get_system_prompt=lambda **_kwargs: "",
    )
