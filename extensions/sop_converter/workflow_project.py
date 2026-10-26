#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.core.workflow_project import (
    logger,
    read_workflow_project_name,
    read_workflow_first_stage_skill_name,
    read_workflow_stage_for_agent,
    read_workflow_stage_pipeline,
    is_prefixed_stage_agent,
)

__all__ = [
    "logger",
    "read_workflow_project_name",
    "read_workflow_first_stage_skill_name",
    "read_workflow_stage_for_agent",
    "read_workflow_stage_pipeline",
    "is_prefixed_stage_agent",
]

from extensions.sop_converter.core import workflow_project as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _impl
