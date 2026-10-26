#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Shared capacity-wake primitive for bridge poll loops.
The implementation merges a long-lived outer abort signal with a short-lived
"wake" controller so a poll loop can sleep while at capacity but wake early
when (a) the outer shutdown signal fires, or (b) capacity frees up (session
done / transport lost). This Python port substitutes ``asyncio.Event`` for
``AbortSignal`` and tracks per-``signal()``-call cleanup so callers can release
listeners deterministically when their sleep resolves normally.
The Python API mirrors:
* ``CapacityWake.signal()`` returns a ``CapacitySignal`` whose ``.event`` is
  set when *either* the outer signal or the wake controller fires. Callers
  use ``await wait_first(event,...)`` or ``await event.wait()`` then call
  ``cleanup()`` to detach listeners.
* ``CapacityWake.wake()`` aborts the current wake controller and arms a
  fresh one so subsequent ``signal()`` calls return a new pair.
Originally lived at
``src/bridge/capacity_wake.py``; moved to ``cloudagent_ext/`` during the single-layering
refactor. The ``src/`` compatibility facade was removed along with it,
so import the ``cloudagent_ext`` path directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable


@dataclass
class CapacitySignal:
    """A merged signal that fires when either source fires.
    ``event`` is an ``asyncio.Event`` that becomes set when *either* the outer
    signal or the wake controller fires. ``cleanup`` detaches the listeners
    so the caller's sleep can release resources when it resolves normally.
    """

    event: asyncio.Event
    cleanup: Callable[[], None]


class CapacityWake:
    """Wake-on-demand abstraction for bridge poll loops.
    See module docstring. Single-loop use only — concurrent ``wake()`` from
    different asyncio tasks is undefined; callers serialize externally.
    """

    def __init__(self, outer_signal: asyncio.Event) -> None:
        self._outer_signal = outer_signal
        self._wake_event = asyncio.Event()

    def wake(self) -> None:
        """Abort the current at-capacity sleep and arm a fresh wake event.
        fires immediately (its merged event becomes set), and any subsequent
        ``signal()`` call returns a fresh pair tied to a new internal event.
        """
        previous = self._wake_event
        self._wake_event = asyncio.Event()
        previous.set()

    def signal(self) -> CapacitySignal:
        """Build a merged signal for a single at-capacity sleep.
        The returned ``event`` is set when either the outer signal or this
        wake controller fires. ``cleanup`` cancels the background watcher
        tasks; callers should call it when their sleep resolves normally so
        the tasks don't leak. If either source has already fired by the time
        ``signal()`` is called, the merged event is returned pre-set with a
        no-op cleanup (matches short-circuit on lines 39-42).
        **Async constraint**: Must be called from inside a running asyncio
        event loop — ``signal()`` spawns watcher tasks via
        ``asyncio.create_task`` which raises ``RuntimeError`` if invoked
        from sync code with no current loop. The short-circuit path (either
        source pre-fired) avoids this and is safe to call from sync code,
        but callers must not rely on that behavior.
        """
        merged = asyncio.Event()

        if self._outer_signal.is_set() or self._wake_event.is_set():
            merged.set()
            return CapacitySignal(event=merged, cleanup=lambda: None)

        # Snapshot the current wake event: if wake() is called between this
        # signal() returning and the caller awaiting, we still want to fire
        # via the *original* event (matches captured-binding semantics on
        # where capSig = wakeController.signal).
        wake_event = self._wake_event
        outer_signal = self._outer_signal

        async def _watch_outer() -> None:
            await outer_signal.wait()
            merged.set()

        async def _watch_wake() -> None:
            await wake_event.wait()
            merged.set()

        outer_task = asyncio.create_task(_watch_outer())
        wake_task = asyncio.create_task(_watch_wake())

        def _cleanup() -> None:
            outer_task.cancel()
            wake_task.cancel()

        return CapacitySignal(event=merged, cleanup=_cleanup)


def create_capacity_wake(outer_signal: asyncio.Event) -> CapacityWake:
    """Factory mirroring ``createCapacityWake(outerSignal)``."""
    return CapacityWake(outer_signal)


__all__ = ["CapacityWake", "CapacitySignal", "create_capacity_wake"]
