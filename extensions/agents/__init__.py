#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Third-party agent extension helpers.

A third-party extension is any subdirectory of ``extensions/`` that
contains an ``agents/`` subdirectory. ``*.md`` files inside ``agents/``
are picked up by
:func:`cloudagent_ext.agent.markdown_discovery.discover_extension_agents`
and registered as ``source="extensions"`` agents, taking priority over
``cloudagent_ext`` but yielding to user / project / managed overrides.

For programmatic registration, import :func:`register` from this module;
it defaults registrations to ``source="extensions"``. Extensions can also
use :class:`cloudagent_ext.agent.registry.AgentRegistry` directly when they
need full control.
"""

from __future__ import annotations

from typing import Callable

from cloudagent_ext.agent.registry import AgentRegistry, SOURCE_EXTENSIONS  # pylint: disable=import-error


def register(
    agent_type: str,
    *,
    when_to_use: str,
    tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
    model: str | None = None,
    permission_mode: str | None = None,
    max_turns: int | None = None,
    background: bool = False,
    color: str | None = None,
    memory: str | None = None,
    omit_claude_md: bool = False,
    skills: list[str] | None = None,
    isolation: str | None = None,
    base_dir: str = "extensions",
) -> Callable[[Callable[..., str]], object]:
    return AgentRegistry.register(
        agent_type,
        when_to_use=when_to_use,
        tools=tools,
        disallowed_tools=disallowed_tools,
        model=model,
        permission_mode=permission_mode,
        max_turns=max_turns,
        background=background,
        color=color,
        memory=memory,
        omit_claude_md=omit_claude_md,
        skills=skills,
        isolation=isolation,
        source=SOURCE_EXTENSIONS,
        base_dir=base_dir,
    )


__all__ = ["register"]
