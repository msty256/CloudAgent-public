#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Deliver formatted orchestrator events through an injected channel callback."""

from __future__ import annotations

import logging
from collections.abc import Callable

from .events.formatter import format_event
from .events.types import OrchestratorEvent

logger = logging.getLogger(__name__)


class ChannelProgressSink:
    """Format events and pass them to the configured channel callback."""

    def __init__(
        self,
        deliver: Callable[[OrchestratorEvent, str], None],
    ) -> None:
        self._deliver = deliver

    def __call__(self, event: OrchestratorEvent) -> None:
        text = format_event(event)
        try:
            self._deliver(event, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ChannelProgressSink deliver failed error_type=%s",
                type(exc).__name__,
            )


__all__ = ["ChannelProgressSink"]
