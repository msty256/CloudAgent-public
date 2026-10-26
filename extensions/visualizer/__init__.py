#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Local Session Visualizer.

A standalone web application for visualizing agent execution sessions
via Gantt charts, timelines, and performance analytics.
"""

from __future__ import annotations

__version__ = "0.1.0"

# The asciicast dashboard source adapter used to live here and
# was reverse-registered into ``extensions.agent_dashboard`` on import.
# The adapter moved to ``extensions.recording.visualizer_dashboard_source``
# where its real consumer (``extensions.recording._factories._visualizer_factory``)
# lives. Recording's factory loader imports it lazily so a partial
# checkout that lacks the recording extension cannot break the
# visualizer import path. No module-level registration happens here.
