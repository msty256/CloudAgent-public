#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Agent Dashboard — Agent model tools.

The :class:`DashboardGet` and :class:`DashboardList` tools expose
the dashboard's read-only snapshot to the model. They mirror the
:func:`/dashboard` command's semantics (per-source filters, status
filter, etc.) so the model and the user see a consistent view.

Both tools honour the plan §4.3 "read-only" invariant:
they never call any subsystem's write methods, and
``is_read_only`` is wired to ``True`` so the agent-loop's
permission layer treats them as observability tools.

The tools are registered in :data:`ALL_STATIC_TOOLS` for the
default tool pool, but the public surface is the two tool
instances (``DashboardGetTool`` / ``DashboardListTool``) so
other registries (test fixtures, the visualizer's "debug"
pool) can opt in independently.
"""

from __future__ import annotations

from .dashboard_get import DashboardGetTool
from .dashboard_list import DashboardListTool

__all__ = [
    "DashboardGetTool",
    "DashboardListTool",
]
