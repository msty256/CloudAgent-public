#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Bounded parallel provider invocation."""

from __future__ import annotations

import asyncio
from typing import Any

from cloudagent_ext.capabilities.multimodel_protocol import MultiModelResult  # pylint: disable=no-name-in-module
from cloudagent_ext.providers.base import MessageInput

from .base import MultiModelStrategyBase


class ParallelStrategy(MultiModelStrategyBase):
    """Send the same request to every enabled slot concurrently."""

    name = "parallel"

    async def execute(self, router: Any, messages: list[MessageInput], **kwargs: Any) -> list[MultiModelResult]:
        slots = [slot for slot in router.slots if slot.enabled]
        if not slots:
            return []
        semaphore = asyncio.Semaphore(router.config.max_concurrent)

        async def call(slot: Any) -> MultiModelResult:
            async with semaphore:
                return await router._call_slot(slot, messages, **kwargs)

        return list(await asyncio.gather(*(call(slot) for slot in slots)))
