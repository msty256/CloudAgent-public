#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Six-class inbound message semantics (P5).

Classifier → CommandRouter → ControlBridge → InboundRuntimeRouter.
No natural-language auto-judgment for ``interrupt``/``contextOnly``;
both require structured metadata or existing control/bridge entry points.
"""

from __future__ import annotations

from .classifier import MessageClassifier
from .command_router import CommandRoute, CommandRouter
from .control_bridge import ControlBridge, ControlTarget
from .runtime_router import InboundRuntimeRouter, RoutingDecision

__all__ = [
    "CommandRoute",
    "CommandRouter",
    "ControlBridge",
    "ControlTarget",
    "InboundRuntimeRouter",
    "MessageClassifier",
    "RoutingDecision",
]
