#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Line-level diff model for two expanded model outputs."""

from __future__ import annotations

import difflib


class DiffDisplay:
    def __init__(self, slots: list[str]) -> None:
        self.slots = slots
        self.left_index = 0
        self.right_index = 1 if len(slots) > 1 else 0
        self.scroll_offset = 0

    def cycle_pair(self, delta: int) -> tuple[str, str]:
        if len(self.slots) > 1:
            self.right_index = (self.right_index + delta) % len(self.slots)
            if self.right_index == self.left_index:
                self.right_index = (self.right_index + delta) % len(self.slots)
        return self.pair

    @property
    def pair(self) -> tuple[str, str]:
        return self.slots[self.left_index], self.slots[self.right_index]

    def lines(self, left: str, right: str) -> list[str]:
        return list(difflib.ndiff(left.splitlines(), right.splitlines()))
