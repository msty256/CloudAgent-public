#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Stage capability mapping."""

from .models import (
    Capability,
    CapabilityKind,
    ExecutionMode,
    StageAgentMap,
    StageCapabilityProfile,
)
from .mapper import StageCapabilityMapper, ensure_stage_skills


def ensure_arc_stage_skills(*args, **kwargs):
    """Lazy wrapper so ARC support is not imported until first use."""
    from .arc_mapper import ensure_arc_stage_skills as _impl

    return _impl(*args, **kwargs)


__all__ = [
    "Capability",
    "CapabilityKind",
    "ExecutionMode",
    "StageAgentMap",
    "StageCapabilityProfile",
    "StageCapabilityMapper",
    "ensure_stage_skills",
    "ensure_arc_stage_skills",
]
