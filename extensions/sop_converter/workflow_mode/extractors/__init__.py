#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Workflow structure extractors."""

from .models import (
    DecisionSpec,
    ExtractedStage,
    GateSpec,
    OutcomeSpec,
    StageContract,
    Transition,
    WorkflowGraph,
)
from .preview import format_workflow_preview
from .pattern import PatternExtractor, PipelineConfig
from .registry import ExtractorRegistry

__all__ = [
    "WorkflowGraph",
    "ExtractedStage",
    "Transition",
    "GateSpec",
    "DecisionSpec",
    "OutcomeSpec",
    "StageContract",
    "PatternExtractor",
    "PipelineConfig",
    "ExtractorRegistry",
    "format_workflow_preview",
]
