#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.runtime.cross_domain_orchestration import (
    ORCHESTRATION_ROUTES_NAME,
    ORCHESTRATION_ROUTES_MAX,
    OrchestrationStep,
    OrchestrationRoute,
    skill_name_to_agent,
    build_tool_to_agent_map,
    discover_orchestration_routes,
    generate_orchestration_routes_markdown,
    write_orchestration_routes,
    format_orchestration_routes_block,
)

__all__ = [
    "ORCHESTRATION_ROUTES_NAME",
    "ORCHESTRATION_ROUTES_MAX",
    "OrchestrationStep",
    "OrchestrationRoute",
    "skill_name_to_agent",
    "build_tool_to_agent_map",
    "discover_orchestration_routes",
    "generate_orchestration_routes_markdown",
    "write_orchestration_routes",
    "format_orchestration_routes_block",
]

from extensions.sop_converter.runtime import cross_domain_orchestration as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
