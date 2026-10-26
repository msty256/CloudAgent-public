#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Timing assertions that survive coarse OS clocks and loaded runners.

Two tests in this suite assert that one event follows another "promptly".
Those tolerances were calibrated on an idle Linux runner.  Two platform facts
break them elsewhere:

* **Coarse clock.** Windows quantises ``time.monotonic()`` to the ~15.6 ms
  system timer tick, so a sub-tick gap is simply *not measurable* — it reads
  either ``0`` or one full tick (16 ms), regardless of what the code did.
  ``time.get_clock_info("monotonic").resolution`` reports the tick.

* **Scheduler jitter.** Under a parallel run (``-n 8``) on Windows, process and
  thread scheduling can add tens of milliseconds to any single scheduling
  decision, independent of the logic under test.

``timing_tolerance_ms`` widens a requested budget to the smallest value that is
both meaningful on the host and not flaky.  The assertions keep their ordering
guarantees (``a_after_b``) either way — only the *duration* bound is relaxed.
"""

from __future__ import annotations

import os
import time

__all__ = ["CLOCK_RESOLUTION_MS", "IS_WINDOWS", "timing_tolerance_ms"]

# One system-timer tick, in milliseconds (Linux: ~1e-6ms, Windows: ~15.6ms).
CLOCK_RESOLUTION_MS = time.get_clock_info("monotonic").resolution * 1000

IS_WINDOWS = os.name == "nt"

# Parallel-run scheduler jitter measured on Windows.  Chosen to stay well below
# the serialisation delays these tests are meant to catch (a wrongly
# serialised pair of callbacks drifts by whole sleeps, not by tens of ms).
_PLATFORM_JITTER_MS = 250.0 if IS_WINDOWS else 0.0


def timing_tolerance_ms(ideal_ms: float, *, jitter_ms: float | None = None) -> float:
    """Return a duration bound that is measurable and stable on this host.

    Parameters
    ----------
    ideal_ms
        The budget the assertion was written with (tuned for a Linux runner).
    jitter_ms
        Override for the platform jitter allowance; defaults to
        ``_PLATFORM_JITTER_MS``.
    """
    jitter = _PLATFORM_JITTER_MS if jitter_ms is None else jitter_ms
    return max(float(ideal_ms), CLOCK_RESOLUTION_MS * 2, jitter)
