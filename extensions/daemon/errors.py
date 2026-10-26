# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Custom exceptions raised by the daemon subsystem."""

from __future__ import annotations


class DaemonError(Exception):
    """Base class for all daemon errors; catching it covers every subclass."""


class UnknownWorkerKindError(DaemonError, KeyError):
    """The requested worker kind is not registered."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"unknown worker kind: {kind!r}")
        self.kind = kind


class PermanentWorkerError(DaemonError):
    """Signal from a worker that it should not be restarted."""

    def __init__(self, message: str = "permanent worker failure") -> None:
        super().__init__(message)


class WorkerSpawnError(DaemonError):
    """The supervisor failed to spawn a worker subprocess."""


class DaemonAlreadyRunningError(DaemonError):
    """``daemon start`` refused because another instance owns the state file."""


class DaemonNotRunningError(DaemonError):
    """``daemon stop`` / ``daemon status`` called but no live daemon found."""


class InvalidDaemonConfigError(DaemonError, ValueError):
    """``DaemonConfig`` failed validation; also a :class:`ValueError`."""
