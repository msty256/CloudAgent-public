#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Pure key-routing state machine for the two multi-model display phases."""

from __future__ import annotations

from .protocol import DisplayPhase


class MultiModelKeyboard:
    """Translate physical keys into stable, UI-independent actions."""

    def action_for(self, phase: DisplayPhase, key: str) -> str | None:
        key = key.lower()
        if phase is DisplayPhase.STREAMING:
            return {
                "left": "previous_tab",
                "right": "next_tab",
                "up": "scroll_up",
                "down": "scroll_down",
                "enter": "waiting",
                "f3": "toggle_columns",
            }.get(key)
        if phase is DisplayPhase.SELECTION:
            return {
                "up": "previous_result",
                "down": "next_result",
                "right": "expand",
                "left": "collapse",
                "enter": "adopt",
                "f2": "toggle_diff",
                "f3": "toggle_columns",
                "escape": "cancel",
                "q": "cancel",
            }.get(key)
        return None
