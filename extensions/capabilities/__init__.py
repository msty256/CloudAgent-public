# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""capabilities — Layer 2: CloudAgent-specific Protocol definitions.

Stub Protocol contracts forming the boundary between Layer 1 (upstream
compat) and Layer 3 (features). See docs/UPSTREAM_SYNC_DESIGN-decoupling.md
section 4.2.
"""

from .agent_protocol import AgentLoopProtocol, AgentLoopResultProtocol
from .dashboard_entry import (
    DASHBOARD_STATUSES,
    DashboardEntry,
    DashboardSink,
    DashboardSource,
    filter_entries,
    normalize_source_name,
)
from .task_protocol import (
    RemoteTaskWorker,
    TaskExecutor,
    TaskRequest,
    TaskResult,
    TaskTransportClient,
    TaskTransportServer,
)
from .tool_protocol import (
    ToolContextProtocol,
    ToolPermissionContextProtocol,
    ToolProtocol,
    ToolRegistryProtocol,
    ToolSystemProtocol,
)
from .context_protocol import ContextBuilderProtocol
from .provider_protocol import LLMProviderProtocol
from .event_protocol import ToolEventProtocol
from .headless_protocol import HeadlessOptionsProtocol, HeadlessRunnerProtocol
from .headless_runner import HeadlessSessionOptions, run_headless_session
from .adapter_protocol import (  # noqa: F401
    AdapterInfo,
    AdapterProtocol,
    AdapterRegistry,
    dependency_available,
    env_switch,
    is_provider_adapter,
)

__all__ = [
    "AdapterInfo",
    "AdapterProtocol",
    "AdapterRegistry",
    "AgentLoopProtocol",
    "AgentLoopResultProtocol",
    "ContextBuilderProtocol",
    "DASHBOARD_STATUSES",
    "DashboardEntry",
    "DashboardSink",
    "DashboardSource",
    "HeadlessOptionsProtocol",
    "HeadlessRunnerProtocol",
    "HeadlessSessionOptions",
    "LLMProviderProtocol",
    "RemoteTaskWorker",
    "TaskExecutor",
    "TaskRequest",
    "TaskResult",
    "TaskTransportClient",
    "TaskTransportServer",
    "ToolContextProtocol",
    "ToolEventProtocol",
    "ToolPermissionContextProtocol",
    "ToolProtocol",
    "ToolRegistryProtocol",
    "ToolSystemProtocol",
    "dependency_available",
    "env_switch",
    "filter_entries",
    "is_provider_adapter",
    "normalize_source_name",
    "run_headless_session",
]
