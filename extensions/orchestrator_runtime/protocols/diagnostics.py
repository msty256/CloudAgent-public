#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""DiagnosticsProbe protocol.

The orchestrator heartbeat loop calls ``DiagnosticsProbe.heartbeat()``
to detect process freeze or deadlock. Concrete backends provide the probe;
the runtime package only owns this boundary contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

HeartbeatState = Literal["alive", "frozen", "stalled"]


@dataclass(slots=True)
class HeartbeatStatus:
    """Result of one ``heartbeat()`` snapshot.

    Attributes:
        state: ``alive`` / ``frozen`` / ``stalled``
        last_tick_age: seconds since the last tick the watcher observed
        detail: optional free-form context (free-form string)
    """

    state: HeartbeatState
    last_tick_age: float
    detail: str = ""


@runtime_checkable
class DiagnosticsProbe(Protocol):
    """Called by orchestrator heartbeat loop."""

    def heartbeat(self) -> HeartbeatStatus: ...


__all__ = ["DiagnosticsProbe", "HeartbeatState", "HeartbeatStatus"]
