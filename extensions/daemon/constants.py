# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Constants for the daemon subsystem."""

from __future__ import annotations

EXIT_CODE_PERMANENT: int = 78

EXIT_CODE_TRANSIENT: int = 1

EXIT_CODE_OK: int = 0

BACKOFF_INITIAL_MS: int = 2_000

BACKOFF_CAP_MS: int = 120_000

BACKOFF_MULTIPLIER: int = 2

MAX_RAPID_FAILURES: int = 5

RAPID_FAILURE_WINDOW_MS: int = 10_000

GRACEFUL_SHUTDOWN_TIMEOUT_MS: int = 30_000

DAEMON_STATE_DIRNAME: str = ".cloudagent"

DAEMON_STATE_SUBDIR: str = "daemon"

DAEMON_STATE_FILENAME_EXT: str = ".json"

ENV_VAR_SUPERVISOR_PID: str = "CLOUDAGENT_SUPERVISOR_PID"
ENV_VAR_DAEMON_NAME: str = "CLOUDAGENT_DAEMON_NAME"
ENV_VAR_DAEMON_DIR: str = "CLOUDAGENT_DAEMON_DIR"
ENV_VAR_DAEMON_SPAWN_MODE: str = "CLOUDAGENT_DAEMON_SPAWN_MODE"
ENV_VAR_DAEMON_CAPACITY: str = "CLOUDAGENT_DAEMON_CAPACITY"
ENV_VAR_DAEMON_PERMISSION_MODE: str = "CLOUDAGENT_DAEMON_PERMISSION_MODE"
ENV_VAR_DAEMON_SANDBOX: str = "CLOUDAGENT_DAEMON_SANDBOX"
ENV_VAR_DAEMON_TIMEOUT_MS: str = "CLOUDAGENT_DAEMON_TIMEOUT_MS"
ENV_VAR_DAEMON_SESSION_KIND: str = "CLOUDAGENT_DAEMON_SESSION_KIND"
