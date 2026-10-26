#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Agent Dashboard — built-in data sources.

This package ships the two data sources the plan §3 commits
to in Phase 2: :class:`GoalDashboardSource` (reads from
``GoalService``) and :class:`TasksDashboardSource` (reads from
``ToolContext.tasks``). Optional Orchestrator / SOP sources live in
``extensions/orchestrator`` and ``extensions/sop_converter`` and
register themselves against the default registry on import.
"""

from __future__ import annotations

from .goal_source import GoalDashboardSource
from .orchestrator_source import OrchestratorDashboardSource
from .sop_source import SOPDashboardSource, register_sop_dashboard_source
from .tasks_source import TasksDashboardSource

__all__ = [
    "GoalDashboardSource",
    "OrchestratorDashboardSource",
    "SOPDashboardSource",
    "TasksDashboardSource",
    "register_sop_dashboard_source",
]
