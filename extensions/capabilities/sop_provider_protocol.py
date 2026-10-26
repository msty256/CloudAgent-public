# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""SOPAssistantProvider Protocol — lightweight chat boundary for SOP grouping.

Trims ``cloudagent_ext.providers.base.BaseProvider`` to the capability
``skill_grouper``'s LLM_SEMANTIC path uses: ``provider.chat(messages) ->
response.content``. Messages accept ``dict[str, Any]`` or ``ChatMessage``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["SOPAssistantProviderProtocol"]


# Mirrors ``cloudagent_ext.providers.base.MessageInput``; typed loosely to
# keep the Protocol duck-typed without dragging the provider package in.
SOPProviderMessage = Any


@runtime_checkable
class SOPAssistantProviderProtocol(Protocol):
    """Single-shot chat boundary used by ``skill_grouper``; MUST return str."""

    def chat(self, messages: list[SOPProviderMessage]) -> str: ...
