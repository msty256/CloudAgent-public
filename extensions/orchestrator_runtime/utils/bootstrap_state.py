#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Orchestrator-local bootstrap-state protocol.

``AgentRunner._save_json_snapshot`` needs the eight cost/timing/line
getters from ``cloudagent_ext.bootstrap.state`` to rebuild a resume
snapshot's cost_block. This protocol exposes them as
``self._bootstrap_state.get_total_cost_usd()`` instead of importing
cloudagent_ext.

Must not import ``cloudagent_ext.*``. Default implementation:
:mod:`extensions.orchestrator_runtime.adapters.cloudagent_bootstrap_state`.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BootstrapState(Protocol):
    """Facade over ``cloudagent_ext.bootstrap.state`` cost/timing getters.

    Default impl (``CloudagentBootstrapState``) forwards every call to the
    upstream module; tests can substitute a stub to control session-level
    accumulators.
    """

    def get_total_cost_usd(self) -> float: ...

    def get_total_api_duration(self) -> int: ...

    def get_total_api_duration_without_retries(self) -> int: ...

    def get_total_tool_duration(self) -> int: ...

    def get_total_lines_added(self) -> int: ...

    def get_total_lines_removed(self) -> int: ...

    def get_start_time(self) -> int | None: ...

    def get_model_usage(self) -> dict[str, Any]: ...


__all__ = ["BootstrapState"]
