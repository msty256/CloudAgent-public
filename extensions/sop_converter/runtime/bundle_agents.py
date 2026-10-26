#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Load per-stage agent markdown from a SOP convert bundle."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

logger = logging.getLogger(__name__)


def register_bundle_agents(bundle_path: Path) -> list[str]:
    """Parse ``.claude/agents/*.md`` in *bundle_path* into AgentRegistry."""
    bundle_path = bundle_path.resolve()
    agents_dir = bundle_path / ".claude" / "agents"
    if not agents_dir.is_dir():
        return []

    from cloudagent_ext.agent.parse_agent_markdown import parse_agent_from_markdown
    from cloudagent_ext.agent.registry import AgentRegistry, SOURCE_EXTENSIONS
    from ..adapters import DEFAULTS

    registered: list[str] = []
    for md_path in sorted(agents_dir.glob("*.md")):
        if not md_path.is_file():
            continue
        try:
            parsed = DEFAULTS.frontmatter_parser(md_path.read_text(encoding="utf-8"))
            agent = parse_agent_from_markdown(
                file_path=str(md_path),
                frontmatter=parsed.frontmatter,
                body=parsed.body,
                source="project",
                base_dir=str(bundle_path),
            )
        except Exception as exc:
            logger.warning("Skip bundle agent %s: %s", md_path.name, exc)
            continue
        if agent is None:
            continue
        agent = replace(agent, source=SOURCE_EXTENSIONS, base_dir=str(bundle_path))
        AgentRegistry.register_definition(agent)
        registered.append(agent.agent_type)
        logger.info("Registered bundle stage agent: %s", agent.agent_type)

    if registered:
        try:
            DEFAULTS.clear_sop_caches()
        except Exception as exc:  # nosec
            logger.warning("Failed to clear SOP caches after bundle agent registration: %s", exc)

    return sorted(set(registered))
