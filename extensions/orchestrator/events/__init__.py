#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Orchestrator → IM event bridge (P3).

Defines the event types, the :class:`OrchestratorEventEmitter` (a
:class:`ProgressSink` that also exposes an explicit ``emit()``), the
event → IM text formatter, and :class:`ChannelProgressSink` that
delivers formatted events to the gateway. Per-sink exception isolation
is baked in so an IM failure never breaks the orchestrator main flow.
"""

from __future__ import annotations

from .emitter import OrchestratorEventEmitter
from .formatter import format_event
from .types import EventLevel, OrchestratorEvent

__all__ = [
    "EventLevel",
    "OrchestratorEvent",
    "OrchestratorEventEmitter",
    "format_event",
]
