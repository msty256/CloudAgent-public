#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.core.sop_prompts import (
    SOP_INTERACTIVE_TERMINAL_STOP_LOSS,
    SOP_SOURCE_EXPLORATION_POLICY,
    SOP_NO_SOURCE_EXPLORATION,
    SOP_TOOL_FAILURE_RECOVERY,
    SOP_TOOLSEARCH_GUIDANCE,
    SOP_OVERVIEW_ROUTING,
    format_sdk_source_dir_block,
    agent_type_to_skill_name,
    pick_pipeline_execute_tool,
    infer_stage_label_from_skill,
    stage_agent_sop_body,
    domain_agent_sop_body,
    format_overview_stage_pipeline_block,
    append_sop_overview_routing,
)

__all__ = [
    "SOP_INTERACTIVE_TERMINAL_STOP_LOSS",
    "SOP_SOURCE_EXPLORATION_POLICY",
    "SOP_NO_SOURCE_EXPLORATION",
    "SOP_TOOL_FAILURE_RECOVERY",
    "SOP_TOOLSEARCH_GUIDANCE",
    "SOP_OVERVIEW_ROUTING",
    "format_sdk_source_dir_block",
    "agent_type_to_skill_name",
    "pick_pipeline_execute_tool",
    "infer_stage_label_from_skill",
    "stage_agent_sop_body",
    "domain_agent_sop_body",
    "format_overview_stage_pipeline_block",
    "append_sop_overview_routing",
]

from extensions.sop_converter.core import sop_prompts as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
