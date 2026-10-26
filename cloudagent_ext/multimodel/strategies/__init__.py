#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Scheduling strategies used by :class:`MultiModelRouter`."""

from .base import MultiModelStrategyBase
from .fallback import FallbackStrategy
from .parallel import ParallelStrategy
from .routing import RoutingRule, RoutingStrategy
from .voting import VotingStrategy

__all__ = [
    "FallbackStrategy",
    "MultiModelStrategyBase",
    "ParallelStrategy",
    "RoutingRule",
    "RoutingStrategy",
    "VotingStrategy",
]
