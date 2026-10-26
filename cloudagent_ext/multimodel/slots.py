#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Runtime description of a provider participating in a model group."""

from __future__ import annotations

from dataclasses import dataclass

from cloudagent_ext.providers.base import BaseProvider


@dataclass(frozen=True)
class ProviderSlot:
    """A provider and the policy used when the router invokes it."""

    name: str
    provider: BaseProvider
    model: str | None = None
    weight: float = 1.0
    timeout_ms: int = 120_000
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("provider slot name must not be empty")
        if self.weight <= 0:
            raise ValueError("provider slot weight must be greater than zero")
        if self.timeout_ms <= 0:
            raise ValueError("provider slot timeout_ms must be greater than zero")
