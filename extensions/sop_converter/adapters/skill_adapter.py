#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Default adapters for :class:`SkillProtocol` and :class:`SkillFrontmatterProtocol`.

Wraps ``cloudagent_ext.skills.model.Skill`` as a factory function and
``cloudagent_ext.skills.frontmatter.parse_frontmatter`` as a callable
so the SOP converter can work with skills without importing
``cloudagent_ext`` directly.

Field names are 1:1 between the upstream dataclass and the Protocol,
so no property aliasing is needed.

See ``docs/DECOUPLE_SOP_CONVERTER_PLAN.md`` §3.4.
"""

from __future__ import annotations

import logging
from typing import Any

from extensions.capabilities.skill_protocol import (
    SkillFrontmatterProtocol,
    SkillFrontmatterResultProtocol,
    SkillProtocol,
)

logger = logging.getLogger(__name__)

__all__ = [
    "default_skill_factory",
    "default_frontmatter_parser",
    "default_clear_sop_caches",
]


def default_clear_sop_caches() -> None:
    """Clear runtime caches (commands, context, agent definitions) after loading
    bundle skills or agents.

    Wraps ``cloudagent_ext.command_system.aggregator.clear_commands_cache``,
    ``cloudagent_ext.context_system.prompt_assembly.clear_context_caches``,
    and ``cloudagent_ext.agent.load_agents_dir.clear_agent_definitions_cache``
    so bundle loading code can clear caches without importing ``cloudagent_ext``
    directly.  Each clear failure is logged as a warning so partial cache
    invalidation is diagnosable by the caller.
    """
    try:
        from cloudagent_ext.command_system.aggregator import clear_commands_cache

        clear_commands_cache()
    except Exception as exc:
        logger.warning("Failed to clear commands cache: %s", exc)
    try:
        from cloudagent_ext.context_system.prompt_assembly import clear_context_caches

        clear_context_caches()
    except Exception as exc:
        logger.warning("Failed to clear context caches: %s", exc)
    try:
        from cloudagent_ext.agent.load_agents_dir import clear_agent_definitions_cache

        clear_agent_definitions_cache()
    except Exception as exc:
        logger.warning("Failed to clear agent definitions cache: %s", exc)


def default_skill_factory(**kwargs: Any) -> SkillProtocol:
    """Construct a ``Skill``-compatible instance.

    Accepts the same keyword arguments as
    ``cloudagent_ext.skills.model.Skill``.

    All keyword arguments are forwarded verbatim; the upstream dataclass
    field names match the Protocol exactly.
    """
    from cloudagent_ext.skills.model import Skill

    return Skill(**kwargs)


class _FrontmatterWrapper:
    """Wraps ``parse_frontmatter`` as a ``SkillFrontmatterProtocol``.

    The upstream ``FrontmatterParseResult`` dataclass already exposes
    ``.frontmatter`` (dict) and ``.body`` (str), so it trivially
    satisfies ``SkillFrontmatterResultProtocol`` at runtime without
    an adapter.
    """

    def __call__(self, markdown: str) -> SkillFrontmatterResultProtocol:
        from cloudagent_ext.skills.frontmatter import parse_frontmatter

        return parse_frontmatter(markdown)  # type: ignore[return-value]


default_frontmatter_parser: SkillFrontmatterProtocol = _FrontmatterWrapper()
"""Default frontmatter parser singleton.

Usage::

    result = default_frontmatter_parser(markdown_text)
    frontmatter = result.frontmatter  # dict
    body = result.body               # str
"""
