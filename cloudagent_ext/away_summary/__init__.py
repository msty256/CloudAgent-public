#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Away Summary extension package."""

from cloudagent_ext.away_summary.config import AwaySummaryConfig  # pylint: disable=no-name-in-module
from cloudagent_ext.away_summary.controller import AwaySummaryController
from cloudagent_ext.away_summary.service import AwaySummaryService  # pylint: disable=no-name-in-module

__all__ = [
    "AwaySummaryConfig",
    "AwaySummaryController",
    "AwaySummaryService",
]
