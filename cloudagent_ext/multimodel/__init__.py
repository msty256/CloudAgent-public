#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Multi-model scheduling extension.

The router implements the existing provider interface, so it can be injected
without changing core query-loop packages.
"""

from .aggregators import (
    FirstSuccessAggregator,
    FusionAggregator,
    MajorityVoteAggregator,
    PassThroughAggregator,
    RankAggregator,
    ScoringAggregator,
)
from .config import GroupConfig, MultiModelConfig, SlotConfig
from .display import MultiModelBridge
from .factory import build_router
from .router import MultiModelRouter, RouterConfig
from .session_bridge import SessionBridge
from .slots import ProviderSlot
from .strategies import FallbackStrategy, ParallelStrategy, RoutingRule, RoutingStrategy, VotingStrategy

__all__ = [
    "FirstSuccessAggregator",
    "FusionAggregator",
    "MajorityVoteAggregator",
    "PassThroughAggregator",
    "RankAggregator",
    "ScoringAggregator",
    "GroupConfig",
    "MultiModelConfig",
    "SlotConfig",
    "MultiModelBridge",
    "build_router",
    "MultiModelRouter",
    "ParallelStrategy",
    "ProviderSlot",
    "RouterConfig",
    "RoutingRule",
    "RoutingStrategy",
    "FallbackStrategy",
    "SessionBridge",
    "VotingStrategy",
]
