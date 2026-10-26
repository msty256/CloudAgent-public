#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Analytics subsystem.

Event logging, session metadata, and event sinks.
Mirrors TypeScript analytics/ directory.
"""

from __future__ import annotations

from .events import AnalyticsEvent, EventType, get_analytics_sink, log_event, set_analytics_sink
from .metadata import SessionAnalyticsMetadata, collect_session_metadata
from .sink import AnalyticsSink, ConsoleSink, FileSink, NullSink

__all__ = [
    "AnalyticsEvent",
    "AnalyticsSink",
    "ConsoleSink",
    "EventType",
    "FileSink",
    "NullSink",
    "SessionAnalyticsMetadata",
    "collect_session_metadata",
    "get_analytics_sink",
    "log_event",
    "set_analytics_sink",
]
