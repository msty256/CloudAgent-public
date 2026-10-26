#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Default adapter for :class:`SOPAssistantProviderProtocol`.

Wraps ``cloudagent_ext.providers.base.BaseProvider`` so the
``skill_grouper`` LLM-assisted semantic grouping path can use the
thin ``SOPAssistantProviderProtocol`` interface instead of importing
the full provider abstraction.

The adapter extracts ``.content`` from the ``ChatResponse`` returned
by ``BaseProvider.chat()``, matching the Protocol's ``str`` return type.

See ``docs/DECOUPLE_SOP_CONVERTER_PLAN.md`` §3.3.
"""

from __future__ import annotations

from typing import Any

from extensions.capabilities.sop_provider_protocol import (
    SOPAssistantProviderProtocol,
    SOPProviderMessage,
)

__all__ = [
    "SOPAssistantProviderAdapter",
]


class SOPAssistantProviderAdapter(SOPAssistantProviderProtocol):
    """Wraps a ``BaseProvider`` as a thin ``SOPAssistantProviderProtocol``.

    Usage::

        adapter = SOPAssistantProviderAdapter.from_provider(base_provider)
        response_text = adapter.chat([{"role": "user", "content": "..."}])
    """

    def __init__(self, upstream: Any) -> None:
        """Wrap an upstream ``BaseProvider`` instance."""
        self._upstream = upstream

    @classmethod
    def from_provider(cls, provider: Any) -> SOPAssistantProviderAdapter:
        """Construct an adapter from a ``BaseProvider``-compatible object.

        This is the primary entry point for existing code that already
        has a ``BaseProvider`` instance::

            from cloudagent_ext.providers.base import BaseProvider

            provider: BaseProvider = ...
            adapter = SOPAssistantProviderAdapter.from_provider(provider)
        """
        return cls(provider)

    def chat(self, messages: list[SOPProviderMessage]) -> str:
        """Send a chat request and return the response text.

        Delegates to ``BaseProvider.chat(messages)`` and extracts
        ``.content`` from the returned ``ChatResponse``.
        """
        response = self._upstream.chat(messages)
        return response.content  # type: ignore[no-any-return, union-attr]
