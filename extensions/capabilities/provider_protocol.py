# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""LLMProvider Protocol — interface for LLM provider abstraction.

Abstraction boundary between Layer 1 (upstream) and Layer 3 (features);
concrete implementation: src/providers/base.py (BaseProvider).
"""

from __future__ import annotations

from typing import Protocol, Generator

__all__ = ["LLMProviderProtocol"]


class LLMProviderProtocol(Protocol):
    """Protocol for LLM provider abstraction.

    Provides: chat() and streaming chat_stream().
    """

    def chat(
        self,
        messages: "list[MessageInput]",  # noqa: F821
        tools: "list[dict[str, object]] | None" = None,
        **kwargs: object,
    ) -> "ChatResponse": ...  # pragma: no cover  # noqa: F821

    def chat_stream(
        self,
        messages: "list[MessageInput]",  # noqa: F821
        tools: "list[dict[str, object]] | None" = None,
        **kwargs: object,
    ) -> Generator[str, None, None]: ...  # pragma: no cover
