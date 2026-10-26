# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Daemon — long-running supervisor for worker subprocesses."""

from __future__ import annotations

__version__ = "0.1.0"

from .config import (
    DEFAULT_DAEMON_NAME,
    DEFAULT_WORKER_KINDS,
    DaemonConfig,
)
from .constants import (
    BACKOFF_CAP_MS,
    BACKOFF_INITIAL_MS,
    BACKOFF_MULTIPLIER,
    EXIT_CODE_PERMANENT,
    EXIT_CODE_TRANSIENT,
    GRACEFUL_SHUTDOWN_TIMEOUT_MS,
    MAX_RAPID_FAILURES,
    RAPID_FAILURE_WINDOW_MS,
)
from .errors import (
    DaemonAlreadyRunningError,
    DaemonError,
    DaemonNotRunningError,
    InvalidDaemonConfigError,
    PermanentWorkerError,
    UnknownWorkerKindError,
    WorkerSpawnError,
)
from .state import (
    DaemonState,
    DaemonStatus,
    get_state_dir,
    get_state_path,
    is_process_alive,
    make_state,
    query_daemon_status,
    read_daemon_state,
    remove_daemon_state,
    write_daemon_state,
)
from .supervisor import Supervisor
from .worker_registry import WorkerRegistry

__all__ = [
    "__version__",
    "DaemonConfig",
    "DEFAULT_DAEMON_NAME",
    "DEFAULT_WORKER_KINDS",
    "BACKOFF_CAP_MS",
    "BACKOFF_INITIAL_MS",
    "BACKOFF_MULTIPLIER",
    "EXIT_CODE_PERMANENT",
    "EXIT_CODE_TRANSIENT",
    "GRACEFUL_SHUTDOWN_TIMEOUT_MS",
    "MAX_RAPID_FAILURES",
    "RAPID_FAILURE_WINDOW_MS",
    "DaemonAlreadyRunningError",
    "DaemonError",
    "DaemonNotRunningError",
    "InvalidDaemonConfigError",
    "PermanentWorkerError",
    "UnknownWorkerKindError",
    "WorkerSpawnError",
    "DaemonState",
    "DaemonStatus",
    "get_state_dir",
    "get_state_path",
    "is_process_alive",
    "make_state",
    "query_daemon_status",
    "read_daemon_state",
    "remove_daemon_state",
    "write_daemon_state",
    "Supervisor",
    "WorkerRegistry",
]
