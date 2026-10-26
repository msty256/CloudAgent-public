#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Coordinator context provider protocol.

Multi-agent coordinator mode enters and leaves a coordination context
through ``CoordinatorContextProvider``, so orchestrator need not import
``cloudagent_ext.coordinator.mode.coordinator_mode_context``.
"""

from __future__ import annotations
# pylint: disable=W2301

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class CoordinatorContextProvider(Protocol):
    """Bridge over ``cloudagent_ext.coordinator.mode.coordinator_mode_context``.

    Phase 3+ uses this Protocol to decouple orchestrator from cloudagent
    coordinator implementation. Today the ``extensions/orchestrator/`` code
    uses ``coordinator_mode_context`` directly; Phase 3 routes via this
    Protocol.
    """

    def is_active(self) -> bool: ...

    def enter(self, enabled: bool) -> AbstractContextManager[None]:
        """Returns a context manager; entering with ``enabled=True`` flips
        the coordinator-mode gate for the lifetime of the block.

        Mirrors the upstream ``coordinator_mode_context(enabled)`` semantics.
        """
        ...


__all__ = ["CoordinatorContextProvider"]
