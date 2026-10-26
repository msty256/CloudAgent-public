#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Stub mirror.
The upstream file is itself a stub annotated
``// Stub — AssistantSessionChooser not included in source snapshot``.
We mirror the stub here so the parity audit reflects that *both* trees
are intentionally empty. The Python REPL has no interactive picker for
``claude assistant`` yet; this module exists so future ports of
``dialogLaunchers`` / have a real import target with the
same export name (``AssistantSessionChooser``, PascalCase) as the 
source — no rename needed at the call sites.
Originally lived at
``src/assistant/session_chooser.py``; moved to ``cloudagent_ext/`` during the single-layering
refactor. The ``src/`` compatibility facade was removed along with it,
so import the ``cloudagent_ext`` path directly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


def AssistantSessionChooser(  # noqa: N802 — mirrors TS React component name
    sessions: Sequence[Any],
    on_select: Callable[[str], None],
    on_cancel: Callable[[], None],
) -> None:
    """Pick a session to attach to. No-op stub (returns ``None``).
    callers can be ported without changing call sites. Name is PascalCase
    to match the React component export — a future port of
    ``,launchAssistantSessionChooser`` should be able
    to write ``from src.assistant.session_chooser import AssistantSessionChooser``
    without an alias.
    """


__all__ = ["AssistantSessionChooser"]
