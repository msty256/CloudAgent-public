#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Common strategy base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from cloudagent_ext.capabilities.multimodel_protocol import MultiModelResult  # pylint: disable=no-name-in-module
from cloudagent_ext.providers.base import MessageInput


class MultiModelStrategyBase(ABC):
    """Small concrete-friendly base for the scheduling protocol."""

    name: str

    @abstractmethod
    async def execute(self, router: Any, messages: list[MessageInput], **kwargs: Any) -> list[MultiModelResult]:
        """Execute one router turn and retain every attempted result."""
