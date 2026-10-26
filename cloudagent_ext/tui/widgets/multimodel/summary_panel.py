#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from __future__ import annotations
# pylint: disable=E0611

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from cloudagent_ext.multimodel.display.protocol import ModelDisplayState

from .result_card import ModelResultCard


class MultiModelSummaryPanel(Vertical):
    """Completed-results panel; cards retain independent expanded state."""

    def __init__(self, states: list[ModelDisplayState] | None = None) -> None:
        super().__init__()
        self._states = states or []

    def compose(self) -> ComposeResult:
        yield Static("✅ 全部完成", classes="-multimodel-title")
        for index, state in enumerate(self._states):
            card = ModelResultCard()
            card.set_result(state, selected=index == 0)
            yield card

    def set_results(self, states: list[ModelDisplayState], selected: int) -> None:
        self._states = states
        cards = list(self.query(ModelResultCard))
        for index, state in enumerate(states):
            if index < len(cards):
                cards[index].set_result(state, selected=index == selected)
