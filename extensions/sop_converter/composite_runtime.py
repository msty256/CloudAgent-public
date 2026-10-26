#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.runtime.composite_runtime import (
    CompositeResult,
    CompositeWorkflowError,
    CompositeWorkflowRunner,
    CompositeWorkflowSpec,
    CompositeWorkflowStep,
    StepVisibility,
    StepTrace,
    normalize_workflow_output,
)

__all__ = [
    "CompositeResult",
    "CompositeWorkflowError",
    "CompositeWorkflowRunner",
    "CompositeWorkflowSpec",
    "CompositeWorkflowStep",
    "StepVisibility",
    "StepTrace",
    "normalize_workflow_output",
]

from extensions.sop_converter.runtime import composite_runtime as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _impl
