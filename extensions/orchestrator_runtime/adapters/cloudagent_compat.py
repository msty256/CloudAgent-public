#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Compatibility shim: re-export cloudagent_ext symbols for orchestrator.

``extensions/orchestrator/{git_sync,orchestrator,agent_runner,
im_gateway_client,prompt_builder}.py`` can import from this module
instead of ``cloudagent_ext.*`` without changing function bodies.

A one-shot rewrite of every ``from cloudagent_ext.*`` import is
regression-prone. This module forwards the same objects so callers
can switch paths with no behavior change::

    # before
    from cloudagent_ext.utils.git import get_file_status

    # after
    from extensions.orchestrator_runtime.adapters.cloudagent_compat import (
        get_file_status,
    )

Once git_sync / orchestrator talk to the Protocol-based
``GitBackend``, this shim can be removed.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# C8 — git subprocess wrapper & dataclasses
# ---------------------------------------------------------------------------
from cloudagent_ext.utils.git import (  # noqa: F401 — re-export
    FileStatus,
    _run_git,
    get_current_branch,
    get_default_branch,
    get_file_status,
    get_repo_root,
)

# ---------------------------------------------------------------------------
# C7 — LLM API errors
# ---------------------------------------------------------------------------
from cloudagent_ext.services.api.errors import (  # noqa: F401 — re-export
    RateLimitError,
    is_rate_limit_error,
)

# ---------------------------------------------------------------------------
# C5 — Channel capability markers
# ---------------------------------------------------------------------------
from cloudagent_ext.services.channels.capabilities import (  # noqa: F401
    CardUpdateCapability,
    ChannelCapability,
)

# ---------------------------------------------------------------------------
# C2 — Tool execution context
# ---------------------------------------------------------------------------
from cloudagent_ext.tool_system.context import ToolContext  # noqa: F401

# ---------------------------------------------------------------------------
# C5 — IM gateway message models
# ---------------------------------------------------------------------------
from cloudagent_ext.services.im_gateway.models import (  # noqa: F401
    InboundMessage,
    MessageSemantics,
)

# ---------------------------------------------------------------------------
# C5 — Message semantics (CommandRouter + ControlBridge)
# ---------------------------------------------------------------------------
from cloudagent_ext.messaging.semantics import (  # noqa: F401
    CommandRouter,
    ControlBridge,
)

# ---------------------------------------------------------------------------
# C1 — Agent definition guidelines (prompt template hint)
# ---------------------------------------------------------------------------
from cloudagent_ext.agent.agent_definitions import task_v2_guidelines  # noqa: F401


__all__ = [
    "CardUpdateCapability",
    "ChannelCapability",
    "CommandRouter",
    "ControlBridge",
    "FileStatus",
    "InboundMessage",
    "MessageSemantics",
    "RateLimitError",
    "ToolContext",
    "_run_git",
    "get_current_branch",
    "get_default_branch",
    "get_file_status",
    "get_repo_root",
    "is_rate_limit_error",
    "task_v2_guidelines",
]
