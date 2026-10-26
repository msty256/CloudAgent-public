#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Parallel scheduling for aggregator-backed voting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cloudagent_ext.capabilities.multimodel_protocol import AggregatorProtocol, MultiModelResult  # pylint: disable=no-name-in-module
from cloudagent_ext.providers.base import MessageInput

from .parallel import ParallelStrategy


@dataclass
class VotingStrategy(ParallelStrategy):
    """Run candidates in parallel; the router's aggregator picks a response.

    ``aggregator`` is optional to support a self-contained strategy while
    retaining the router-level aggregator injection documented.
    """

    aggregator: AggregatorProtocol | None = None
    min_votes: int = 2
    name = "voting"

    async def execute(self, router: Any, messages: list[MessageInput], **kwargs: Any) -> list[MultiModelResult]:
        return await super().execute(router, messages, **kwargs)
