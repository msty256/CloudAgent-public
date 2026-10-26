#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Canonical public surface for :mod:`cloudagent_ext.skills`."""

from __future__ import annotations

import importlib
from typing import Any

_SYMBOLS_BY_MODULE: dict[str, tuple[str, ...]] = {
    "cloudagent_ext.skills.model": ("Skill", "PromptSkill"),
    "cloudagent_ext.skills.bundled_skills": (
        "BundledSkillDefinition",
        "SkillValidationError",
        "register_bundled_skill",
        "get_bundled_skills",
        "get_bundled_skill_by_name",
        "clear_bundled_skills",
        "validate_skill",
        "validate_skill_definition",
        "skill_from_mcp_tool",
    ),
    "cloudagent_ext.skills.create": ("create_skill",),
    "cloudagent_ext.skills.loader": (
        "create_skill_command",
        "parse_skill_frontmatter_fields",
        "get_skill_dir_commands",
        "get_skills_path",
        "load_skills_from_skills_dir",
        "load_skills_from_dir",
        "discover_skill_dirs_for_paths",
        "add_skill_directories",
        "activate_conditional_skills_for_paths",
        "get_dynamic_skills",
        "get_conditional_skill_count",
        "clear_skill_caches",
        "clear_dynamic_skills",
        "clear_skill_registry",
        "get_all_skills",
        "get_registered_skill",
    ),
    "cloudagent_ext.skills.frontmatter": ("parse_frontmatter",),
    "cloudagent_ext.skills.argument_substitution": (
        "parse_arguments",
        "substitute_arguments",
    ),
    "cloudagent_ext.skills.mcp_skill_builders": (
        "register_mcp_skill_builders",
        "get_mcp_skill_builders",
    ),
    "cloudagent_ext.skills.runtime_substitution": (
        "render_skill_prompt",
        "prepend_base_dir_header",
        "substitute_skill_dir",
        "substitute_session_id",
        "find_shell_blocks",
        "has_shell_blocks",
        "format_shell_output",
        "format_shell_error",
    ),
    "cloudagent_ext.skills.bundled": ("init_bundled_skills",),
}
_SYMBOL_MODULES = {symbol: module_name for module_name, symbols in _SYMBOLS_BY_MODULE.items() for symbol in symbols}

__all__ = list(_SYMBOL_MODULES)


def __getattr__(name: str) -> Any:
    try:
        module_name = _SYMBOL_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value
