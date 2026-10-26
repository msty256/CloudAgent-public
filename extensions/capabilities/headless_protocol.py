# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""HeadlessOptions Protocol — interface for headless session configuration.

Lets ``src/api/query.py`` configure headless sessions without importing
from upstream entrypoints.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO, Protocol

__all__ = ["HeadlessOptionsProtocol"]


class HeadlessOptionsProtocol(Protocol):
    """Protocol for headless run configuration.

    Concrete: src/entrypoints/headless.HeadlessOptions.
    """

    @property
    def prompt(self) -> str | None: ...

    @property
    def output_format(self) -> str: ...

    @property
    def input_format(self) -> str: ...

    @property
    def provider_name(self) -> str | None: ...

    @property
    def model(self) -> str | None: ...

    @property
    def max_turns(self) -> int: ...

    @property
    def permission_mode(self) -> str: ...

    @property
    def is_bypass_permissions_mode_available(self) -> bool: ...

    @property
    def allowed_tools(self) -> tuple[str, ...]: ...

    @property
    def disallowed_tools(self) -> tuple[str, ...]: ...

    @property
    def include_partial_messages(self) -> bool: ...

    @property
    def verbose(self) -> bool: ...

    @property
    def stdin(self) -> IO[str] | None: ...

    @property
    def stdout(self) -> IO[str] | None: ...

    @property
    def stderr(self) -> IO[str] | None: ...

    @property
    def workspace_root(self) -> Path | None: ...


class HeadlessRunnerProtocol(Protocol):
    """Protocol for the headless run function.

    Concrete: src/entrypoints/headless.run_headless.
    """

    def __call__(self, options: HeadlessOptionsProtocol) -> int: ...
