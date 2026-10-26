# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Event Protocol — interface for tool event emission.

Decouples src/api/query.py from the upstream concrete implementation
(src/tool_system/agent_loop.ToolEvent).
"""

from __future__ import annotations

from typing import Any, Protocol

__all__ = ["ToolEventProtocol"]


class ToolEventProtocol(Protocol):
    """Protocol for tool-use / tool-result / tool-error events.

    Concrete: src/tool_system/agent_loop.ToolEvent.
    """

    @property
    def kind(self) -> str: ...

    @property
    def tool_name(self) -> str: ...

    @property
    def tool_input(self) -> dict[str, Any] | None: ...

    @property
    def tool_output(self) -> Any | None: ...

    @property
    def tool_use_id(self) -> str | None: ...

    @property
    def is_error(self) -> bool: ...

    @property
    def error(self) -> str | None: ...
