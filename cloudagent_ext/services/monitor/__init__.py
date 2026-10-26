#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Monitor service layer.

Provides the controller, watch compatibility shim, generic text tail follower,
and stall-watchdog exemption hook used by both the ``/monitor`` slash command
and the ``Monitor`` built-in tool.
"""

from __future__ import annotations

from .controller import MonitorController, MonitorStartResult
from .install import install_monitor_extensions
from .stall_guard import StallWatchdogExemptor
from .text_tail import TextTailBuffer, TextTailFollower
from .watch_compat import normalize_watch_command

__all__ = [
    "MonitorController",
    "MonitorStartResult",
    "StallWatchdogExemptor",
    "TextTailBuffer",
    "TextTailFollower",
    "install_monitor_extensions",
    "normalize_watch_command",
]
