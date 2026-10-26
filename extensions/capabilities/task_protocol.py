# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Remote task execution protocol — Layer 2 Protocol definitions.

Interface contract between daemon workers and external task dispatchers,
agnostic to any specific cloud provider or message queue. Implementations
live in ``extensions/daemon/workers/`` (worker side) and ``cloudagent_ext/``
(client side).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

__all__ = [
    "RemoteTaskWorker",
    "TaskExecutor",
    "TaskRequest",
    "TaskResult",
    "TaskTransportClient",
    "TaskTransportServer",
]


# Data models


@dataclass(frozen=True)
class TaskRequest:
    """Task request from an external dispatcher; ``id`` is dispatcher-assigned."""

    id: str
    command: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult:
    """Task execution result."""

    task_id: str
    status: str
    output: str = ""
    error: str = ""
    exit_code: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


# Transport protocols


@runtime_checkable
class TaskTransportServer(Protocol):
    """Worker-side task transport: listens for requests, sends results."""

    async def serve(self, cancel_event: Any | None = None) -> None:
        """Start the transport server; ``cancel_event`` triggers graceful shutdown."""

    async def shutdown(self) -> None:
        """Stop the transport server and release resources."""


@runtime_checkable
class TaskTransportClient(Protocol):
    """Dispatcher-side transport client: connects, sends, receives."""

    async def connect(self) -> None: ...

    async def send_request(self, request: TaskRequest) -> TaskResult:
        """Send a request and await the result."""

    async def close(self) -> None: ...


# Execution layer


@runtime_checkable
class TaskExecutor(Protocol):
    """Task executor — takes a TaskRequest, produces a TaskResult."""

    async def execute(self, request: TaskRequest) -> TaskResult:
        """Execute one task."""

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running task; ``True`` if cancelled, ``False`` if unknown."""


# Worker contract


@runtime_checkable
class RemoteTaskWorker(Protocol):
    """Overall contract for a remote task execution worker."""

    kind: str

    async def run(self, env: dict[str, str]) -> int:
        """Run the worker main loop.

        Exit codes: ``0`` normal, ``78`` permanent error, other = transient error.
        """

    def health_check(self) -> dict[str, Any] | None:
        """Optional health snapshot or ``None``."""
