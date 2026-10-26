#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""LLMProvider marker protocol.

Provider lifecycle belongs to ``AgentRuntime``, not the orchestrator
protocol surface. This type exists only as a provider identity so
orchestrator never imports a concrete provider class.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Marker — the orchestrator never calls provider directly. It's passed
    by name to ``AgentRuntime.stream()``; AgentRuntime owns the provider
    lifecycle.
    """

    name: str
    model: str


__all__ = ["LLMProvider"]
