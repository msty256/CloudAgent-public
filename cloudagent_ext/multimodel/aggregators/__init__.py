#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Public multi-model response aggregators."""

from .first_success import FirstSuccessAggregator
from .fusion import FusionAggregator
from .majority_vote import MajorityVoteAggregator
from .passthrough import PassThroughAggregator
from .rank import RankAggregator
from .scoring import ScoringAggregator

__all__ = [
    "FirstSuccessAggregator",
    "FusionAggregator",
    "MajorityVoteAggregator",
    "PassThroughAggregator",
    "RankAggregator",
    "ScoringAggregator",
]
