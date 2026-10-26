#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Sequential failover scheduling."""

from __future__ import annotations

from typing import Any

from cloudagent_ext.capabilities.multimodel_protocol import MultiModelResult  # pylint: disable=no-name-in-module
from cloudagent_ext.providers.base import MessageInput

from .base import MultiModelStrategyBase


class FallbackStrategy(MultiModelStrategyBase):
    """Try enabled slots in order and stop after the first successful call."""

    name = "fallback"

    async def execute(self, router: Any, messages: list[MessageInput], **kwargs: Any) -> list[MultiModelResult]:
        results: list[MultiModelResult] = []
        for slot in router.slots:
            if not slot.enabled:
                continue
            result = await router._call_slot(slot, messages, **kwargs)
            results.append(result)
            if result.error is None and not result.cancelled:
                break
        return results
