#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Capabilities bridge — re-exports from extensions.capabilities.

This module exists so adapter modules in ``cloudagent_ext/`` can import
from a stable path without depending directly on ``extensions/``
internal structure.  All definitions live in
``extensions/capabilities/``.
"""

from extensions.capabilities.adapter_protocol import (  # noqa: F401
    AdapterInfo,
    AdapterProtocol,
    AdapterRegistry,
    dependency_available,
    env_switch,
    is_provider_adapter,
)
from extensions.capabilities.agent_protocol import (  # noqa: F401
    AgentLoopProtocol,
    AgentLoopResultProtocol,
)
from extensions.capabilities.context_protocol import (  # noqa: F401
    ContextBuilderProtocol,
)
from extensions.capabilities.event_protocol import (  # noqa: F401
    ToolEventProtocol,
)
from extensions.capabilities.headless_protocol import (  # noqa: F401
    HeadlessOptionsProtocol,
    HeadlessRunnerProtocol,
)
from extensions.capabilities.headless_runner import (  # noqa: F401
    HeadlessSessionOptions,
    run_headless_session,
)
from extensions.capabilities.provider_protocol import (  # noqa: F401
    LLMProviderProtocol,
)
from extensions.capabilities.tool_protocol import (  # noqa: F401
    ToolContextProtocol,
    ToolPermissionContextProtocol,
    ToolProtocol,
    ToolRegistryProtocol,
    ToolSystemProtocol,
)
from .multimodel_protocol import (  # noqa: F401
    AggregatedOutput,
    AggregatorProtocol,
    MultiModelResult,
    MultiModelStrategy,
)

__all__ = [
    "AdapterInfo",
    "AdapterProtocol",
    "AdapterRegistry",
    "AggregatedOutput",
    "AggregatorProtocol",
    "AgentLoopProtocol",
    "AgentLoopResultProtocol",
    "ContextBuilderProtocol",
    "HeadlessOptionsProtocol",
    "HeadlessRunnerProtocol",
    "HeadlessSessionOptions",
    "LLMProviderProtocol",
    "MultiModelResult",
    "MultiModelStrategy",
    "ToolContextProtocol",
    "ToolEventProtocol",
    "ToolPermissionContextProtocol",
    "ToolProtocol",
    "ToolRegistryProtocol",
    "ToolSystemProtocol",
    "dependency_available",
    "env_switch",
    "is_provider_adapter",
    "run_headless_session",
]
