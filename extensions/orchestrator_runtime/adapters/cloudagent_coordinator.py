#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""CloudagentCoordinatorProvider — concrete ``CoordinatorContextProvider`` adapter.

Thin wrapper over ``coordinator_mode_context`` / ``is_coordinator_mode``
so agent_runner does not import ``cloudagent_ext.coordinator.mode``.

``enter()`` returns the upstream context manager. ``is_active()``
forwards ``is_coordinator_mode()``. No local state — each call hits
upstream, matching the original behavior.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from extensions.orchestrator_runtime.protocols.coordinator import (
    CoordinatorContextProvider,
)

if TYPE_CHECKING:
    pass


class CloudagentCoordinatorProvider(CoordinatorContextProvider):
    """Forward to ``cloudagent_ext.coordinator.mode``."""

    def is_active(self) -> bool:
        from cloudagent_ext.coordinator.mode import is_coordinator_mode

        return bool(is_coordinator_mode())

    def enter(self, enabled: bool = True) -> AbstractContextManager[None]:
        from cloudagent_ext.coordinator.mode import coordinator_mode_context

        # Pass through the ``enabled`` flag so callers (e.g. agent_runner.run)
        # can keep their dynamic coordinator-mode toggle semantics.
        return coordinator_mode_context(enabled)  # type: ignore[return-value]


__all__ = ["CloudagentCoordinatorProvider"]
