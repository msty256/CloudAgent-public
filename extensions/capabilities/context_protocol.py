# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""ContextBuilder Protocol — interface for context/prompt construction.

Concrete implementation: src/context_system/builder.py (build_context_prompt).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

__all__ = ["ContextBuilderProtocol"]


class ContextBuilderProtocol(Protocol):
    """Protocol for building tool execution context.

    Provides: build_context_prompt(workspace_root, *, cwd) -> str.
    """

    def build_context_prompt(
        self,
        workspace_root: str | Path,
        *,
        cwd: str | Path | None = None,
    ) -> str: ...  # pragma: no cover
