# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""
Bundled Skill Extension — SOP Converter + Dreaming.

Mirrors the src/skills/bundled/ pattern for cloudagent-specific bundled skills.
SOP conversion skill + ``/dream`` skill registered here for skills_ext
integration.
"""

from __future__ import annotations

from cloudagent_ext.skills.bundled_skills import BundledSkillDefinition, register_bundled_skill

from .dream import register_dream_skill


def register_convert_sop_skill() -> bool:
    """Register the convert-sop-to-agent bundled skill."""
    from extensions.sop_converter.convert_sop_skill import get_prompt_for_command

    registered = register_bundled_skill(
        BundledSkillDefinition(
            name="convert-sop-to-agent",
            description=(
                "Convert a Standard Operating Procedure (SOP) into a reusable Agent. "
                "Takes SDK specifications and business requirements, then produces "
                "an AgentDefinition with grouped Skills, SKILL.md files, and optional "
                "agent persistence file for long-term use."
            ),
            get_prompt_for_command=get_prompt_for_command,
            aliases=["sop-to-agent"],
            when_to_use=(
                "When you need to convert a SOP workflow into an agent. "
                "Input: SDK spec (OpenAPI URL/JSON or method list) + requirements."
            ),
            argument_hint="<sdk_spec> [--requirements '<requirements>']",
            allowed_tools=[],
            user_invocable=True,
            disable_model_invocation=True,
            context="inline",
        )
    )
    if not registered:
        raise ValueError("convert-sop-to-agent definition was rejected")
    return True


__all__ = [
    "register_convert_sop_skill",
    "register_dream_skill",
]
