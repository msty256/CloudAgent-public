#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Wide-terminal layout decision and synchronized-scroll state."""

from __future__ import annotations


class SideBySideDisplay:
    MIN_WIDTH = 180

    def __init__(self, terminal_width: int = 0) -> None:
        self.terminal_width = terminal_width
        self.enabled = False
        self.scroll_offset = 0

    @property
    def available(self) -> bool:
        return self.terminal_width >= self.MIN_WIDTH

    def toggle(self) -> bool:
        if self.available:
            self.enabled = not self.enabled
        return self.enabled

    def scroll(self, delta: int) -> int:
        self.scroll_offset = max(0, self.scroll_offset + delta)
        return self.scroll_offset
