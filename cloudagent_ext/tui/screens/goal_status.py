#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Dismissible status view for the Claude-style ``/goal`` command."""

from __future__ import annotations

from collections.abc import Iterator

from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Static

from .dialog_base import DialogScreen


class GoalStatusScreen(DialogScreen[None]):
    """Show local goal state without adding it to transcript scrollback."""

    title_text = "Goal"
    footer_hint = "Esc to dismiss"
    BINDINGS = [
        Binding("escape", "cancel", "Close", show=False),
        Binding("q", "cancel", "Close", show=False),
    ]

    def __init__(self, status_text: str) -> None:
        self._status_text = status_text.strip()
        super().__init__()

    def build_body(self) -> Iterator[Widget]:
        body = self._status_text
        if body.startswith("Goal\n\n"):
            body = body[len("Goal\n\n") :]
        yield Static(body, markup=False)


__all__ = ["GoalStatusScreen"]
