# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Built-in daemon workers.

Importing this package **eagerly** registers the built-in worker
factories with :class:`extensions.daemon.worker_registry.WorkerRegistry`.

Callers that want a clean registry (e.g. tests that override the
``remoteControl`` factory) should call ``WorkerRegistry.reset()``
**before** importing this package.

Worker kinds
------------
* ``remoteControl`` — remote task executor listening on a Unix socket (legacy alias)
* ``task_server``   — remote task executor (same implementation as ``remoteControl``)
* ``cron``          — scheduled task dispatcher
"""

from __future__ import annotations

import logging

from extensions.daemon.worker_registry import WorkerRegistry

from extensions.daemon.workers.base import BaseWorker
from extensions.daemon.workers.cron import CronWorker, build_cron_worker
from extensions.daemon.workers.remote_control import RemoteControlWorker, build_remote_control_worker
from extensions.daemon.workers.task_worker import TaskServerWorker, build_task_server_worker

logger = logging.getLogger(__name__)

# Register built-in workers. Re-registration is allowed; this is the
# canonical place to declare default factories.
WorkerRegistry.register("remoteControl", build_remote_control_worker)
WorkerRegistry.register("task_server", build_task_server_worker)
WorkerRegistry.register("cron", build_cron_worker)

__all__ = [
    "BaseWorker",
    "CronWorker",
    "RemoteControlWorker",
    "TaskServerWorker",
    "build_cron_worker",
    "build_remote_control_worker",
    "build_task_server_worker",
]
