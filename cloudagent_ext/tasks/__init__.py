#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Background-session lifecycle support."""

from __future__ import annotations

from .bg_session import (
    BgSession,
    BgSessionAlreadyRunningError,
    BgSessionAttachError,
    BgSessionConfig,
    BgSessionEvent,
    BgSessionNotFoundError,
    BgSessionOrphanedError,
    BgSessionPermissionError,
    BgSessionStatus,
    BgSessionStopError,
    BgSessionsDisabledError,
    DEFAULT_INDEX_PATH,
    is_bg_sessions_enabled,
    marker_path_for,
    replace_session,
    transcript_path_for,
)
from .bg_session_health import HealthAssessment, assess, reconcile
from .bg_session_registry import BgSessionRegistry
from .bg_session_manager import BgSessionManager

__all__ = [
    "BgSession",
    "BgSessionConfig",
    "BgSessionEvent",
    "BgSessionStatus",
    "BgSessionsDisabledError",
    "BgSessionNotFoundError",
    "BgSessionAlreadyRunningError",
    "BgSessionAttachError",
    "BgSessionPermissionError",
    "BgSessionOrphanedError",
    "BgSessionStopError",
    "DEFAULT_INDEX_PATH",
    "HealthAssessment",
    "assess",
    "is_bg_sessions_enabled",
    "marker_path_for",
    "reconcile",
    "replace_session",
    "transcript_path_for",
    "BgSessionRegistry",
    "BgSessionManager",
]


# ---------------------------------------------------------------------------
# Upstream per-type task registrations (relocated from ``src/tasks/__init__.py``)
# ---------------------------------------------------------------------------
# ``import cloudagent_ext.tasks`` must register every concrete task type in one
# place (the per-type modules no longer carry their own ``_register()`` side
# effect).
from cloudagent_ext.task_registry import register_task  # noqa: E402, F401
from cloudagent_ext.tasks.dream import DreamTask, DreamTaskState  # noqa: E402, F401
from cloudagent_ext.tasks.in_process_teammate import (  # noqa: E402, F401
    InProcessTeammateTask,
    InProcessTeammateTaskState,
)
from cloudagent_ext.tasks.local_agent import (  # noqa: E402, F401
    LocalAgentTask,
    LocalAgentTaskState,
)
from cloudagent_ext.tasks.local_shell import (  # noqa: E402, F401
    LocalShellTask,
    LocalShellTaskState,
)
from cloudagent_ext.tasks.local_workflow import (  # noqa: E402, F401
    LocalWorkflowTask,
    LocalWorkflowTaskState,
)

register_task(LocalShellTask())
register_task(LocalAgentTask())
register_task(InProcessTeammateTask())
register_task(DreamTask())
register_task(LocalWorkflowTask())

__all__ = sorted(set(globals().get("__all__", ())) | {
    "DreamTask",
    "DreamTaskState",
    "InProcessTeammateTask",
    "InProcessTeammateTaskState",
    "LocalAgentTask",
    "LocalAgentTaskState",
    "LocalShellTask",
    "LocalShellTaskState",
    "LocalWorkflowTask",
    "LocalWorkflowTaskState",
    "register_task",
})
