# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``remoteControl`` daemon worker.

A thin wrapper around :class:`TaskServerWorker` — listens on a local
Unix Domain Socket, accepts JSON-lines task requests, and runs agent
tasks in subprocesses. No longer depends on the Anthropic Cloud bridge.

Back-compat
-----------
The ``remoteControl`` kind in :class:`WorkerRegistry` is unchanged, so
existing ``--workers remoteControl`` invocations keep working. The new
``task_server`` kind is an identical implementation for new deploys.

Migration path
--------------
``remoteControl`` will be deprecated in a future release; use
``task_server`` instead.
"""

from __future__ import annotations

import logging

from extensions.daemon.workers.task_worker import TaskServerWorker

logger = logging.getLogger(__name__)


class RemoteControlWorker(TaskServerWorker):
    """``remoteControl`` worker (a ``TaskServerWorker`` alias).

    Keeps ``kind = "remoteControl"`` for backward compatibility.
    """

    kind = "remoteControl"


def build_remote_control_worker() -> RemoteControlWorker:
    """Factory for ``WorkerRegistry.register("remoteControl", ...)``."""
    return RemoteControlWorker()


__all__ = ["RemoteControlWorker", "build_remote_control_worker"]
