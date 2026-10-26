#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Workflow mode package."""

from .discriminator import WorkflowDiscriminator
from .models import DiscriminationResult, HeuristicMatch, THRESHOLD_FWA, THRESHOLD_SDK
from .pipeline import discriminate_and_extract, extract_workflow
from .scan_context import SourceScanContext

__all__ = [
    "WorkflowDiscriminator",
    "DiscriminationResult",
    "HeuristicMatch",
    "THRESHOLD_SDK",
    "THRESHOLD_FWA",
    "SourceScanContext",
    "extract_workflow",
    "discriminate_and_extract",
]
