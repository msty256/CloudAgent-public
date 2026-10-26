#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Default adapter for :class:`AgentDefinitionProtocol`.

Wraps ``cloudagent_ext.agent.agent_definitions.AgentDefinition`` as a
factory function so the SOP converter can construct agent definitions
without importing ``cloudagent_ext`` directly.

Field names are already 1:1 between the upstream dataclass and the
Protocol, so no property aliasing is needed — the factory is a simple
``**kwargs`` passthrough.

See ``docs/DECOUPLE_SOP_CONVERTER_PLAN.md`` §3.4.
"""

from __future__ import annotations

from typing import Any

from extensions.capabilities.agent_definition_protocol import (
    AgentDefinitionProtocol,
)

__all__ = [
    "default_agent_definition_factory",
    "default_agent_loader",
]


def default_agent_definition_factory(**kwargs: Any) -> AgentDefinitionProtocol:
    """Construct an ``AgentDefinition``-compatible instance.

    Accepts the same keyword arguments as
    ``cloudagent_ext.agent.agent_definitions.AgentDefinition``.

    All keyword arguments are forwarded verbatim; no field aliasing is
    needed because the upstream dataclass field names match the Protocol
    exactly.
    """
    from cloudagent_ext.agent.agent_definitions import AgentDefinition

    return AgentDefinition(**kwargs)


def default_agent_loader() -> list[AgentDefinitionProtocol]:
    """Return all known agent definitions.

    Wraps
    ``cloudagent_ext.agent.load_agents_dir.get_agent_definitions_with_overrides``
    using the current working directory as the root.
    """
    import os

    from cloudagent_ext.agent.load_agents_dir import (
        get_agent_definitions_with_overrides,
    )

    return list(get_agent_definitions_with_overrides(os.getcwd()))
