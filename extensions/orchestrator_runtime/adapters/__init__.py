#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Adapters that wrap cloudagent implementations behind runtime protocols.

``cloudagent_compat`` re-exports selected ``cloudagent_ext.*`` symbols so
``extensions.orchestrator`` can switch import paths without changing
call-site behavior.

Concrete adapters (injectable via kwargs on ``AgentRunner`` /
``OrchestratorGatewayClient``):

* :class:`CloudagentAgentRuntime` — wraps ``extensions.api.query.QueryRunner``
* :class:`CloudagentSessionStorage` — wraps ``cloudagent_ext.services.session_storage``
* :class:`CloudagentCoordinatorProvider` — wraps ``cloudagent_ext.coordinator.mode``
* :class:`CloudagentImChannel` — wraps ``OrchestratorGatewayClient``
* :class:`CloudagentBootstrapState` — wraps ``cloudagent_ext.bootstrap.state``

``build_default_*()`` returns a cached singleton. Production code can
call ``build_default_agent_runtime()``; tests replace it with a stub.
"""

from __future__ import annotations

from extensions.orchestrator_runtime.adapters.cloudagent_agent_runtime import (
    CloudagentAgentRuntime,
)
from extensions.orchestrator_runtime.adapters.cloudagent_bootstrap_state import (
    CloudagentBootstrapState,
)
from extensions.orchestrator_runtime.adapters.cloudagent_coordinator import (
    CloudagentCoordinatorProvider,
)
from extensions.orchestrator_runtime.adapters.cloudagent_im_channel import (
    CloudagentImChannel,
)
from extensions.orchestrator_runtime.adapters.cloudagent_session_storage import (
    CloudagentSessionStorage,
)

# ─── Singletons (lazy via module-level globals; tests can ``del`` to reset) ──

_agent_runtime_singleton: CloudagentAgentRuntime | None = None
_session_storage_singleton: CloudagentSessionStorage | None = None
_coordinator_singleton: CloudagentCoordinatorProvider | None = None
_bootstrap_state_singleton: CloudagentBootstrapState | None = None


def build_default_agent_runtime() -> CloudagentAgentRuntime:
    """Return a cached default ``AgentRuntime`` adapter."""
    global _agent_runtime_singleton
    if _agent_runtime_singleton is None:
        _agent_runtime_singleton = CloudagentAgentRuntime()
    return _agent_runtime_singleton


def build_default_session_storage() -> CloudagentSessionStorage:
    """Return a cached default ``SessionStorage`` adapter."""
    global _session_storage_singleton
    if _session_storage_singleton is None:
        _session_storage_singleton = CloudagentSessionStorage()
    return _session_storage_singleton


def build_default_coordinator_provider() -> CloudagentCoordinatorProvider:
    """Return a cached default ``CoordinatorContextProvider`` adapter."""
    global _coordinator_singleton
    if _coordinator_singleton is None:
        _coordinator_singleton = CloudagentCoordinatorProvider()
    return _coordinator_singleton


def build_default_bootstrap_state() -> CloudagentBootstrapState:
    """Return a cached default ``BootstrapState`` adapter."""
    global _bootstrap_state_singleton
    if _bootstrap_state_singleton is None:
        _bootstrap_state_singleton = CloudagentBootstrapState()
    return _bootstrap_state_singleton


def reset_adapters_for_tests() -> None:
    """Drop all singletons so the next ``build_default_*()`` recreates them.

    Tests that want to swap a default implementation should call this after
    patching the underlying module attribute.
    """
    global _agent_runtime_singleton
    global _session_storage_singleton
    global _coordinator_singleton
    global _bootstrap_state_singleton
    _agent_runtime_singleton = None
    _session_storage_singleton = None
    _coordinator_singleton = None
    _bootstrap_state_singleton = None


__all__ = [
    "CloudagentAgentRuntime",
    "CloudagentBootstrapState",
    "CloudagentCoordinatorProvider",
    "CloudagentImChannel",
    "CloudagentSessionStorage",
    "build_default_agent_runtime",
    "build_default_bootstrap_state",
    "build_default_coordinator_provider",
    "build_default_session_storage",
    "reset_adapters_for_tests",
]
