# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""
Skills Extension Layer (skills_ext)

Extends upstream skills loader with cloudagent-specific functionality.
Follows the same pattern as tool_system_ext for consistency.

Architecture:
    src/skills/           - Layer 1: Upstream original code (read-only)
    src/skills_ext/       - Layer 2: cloudagent extension layer (new)

Extension components:
    - SkillRegistryExt: Wrapper for upstream loader with bundle support
    - bundles.py: Skill bundle definitions
    - agent_config.py: Per-agent skill configuration
    - paths.py: cloudagent-specific path resolution
    - hooks.py: Skill lifecycle callbacks
    - cache.py: Extension layer caching
    - bundled/: cloudagent-native bundled skills (SOP converter, etc.)
"""

from .registry_ext import SkillRegistryExt, SkillRegistrationCallback

__all__ = [
    "SkillRegistryExt",
    "SkillRegistrationCallback",
    "init_skill_catalog_extensions",
]


def init_skill_catalog_extensions() -> bool:
    """Ensure extension-owned prompt skills exist in the canonical catalog."""
    from cloudagent_ext.skills.bundled_skills import get_registered_bundled_skills

    if any(skill.name == "convert-sop-to-agent" for skill in get_registered_bundled_skills()):
        return True

    from .bundled import register_convert_sop_skill

    try:
        return register_convert_sop_skill()
    except Exception:
        return False


def init_skills_ext() -> None:
    """Initialize skills_ext bundled skills.

    Registers cloudagent-native skills that are not part of upstream.
    Each skill is registered independently — one failure does not
    block others.
    """
    from .bundled import register_convert_sop_skill, register_dream_skill

    import logging

    logger = logging.getLogger(__name__)
    try:
        register_convert_sop_skill()
    except Exception as exc:
        logger.warning("failed to register convert-sop-to-agent: %s", exc)

    try:
        register_dream_skill()
    except Exception as exc:
        logger.warning("failed to register dream skill: %s", exc)
