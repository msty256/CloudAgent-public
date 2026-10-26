#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""CLI exit helpers.
Port. Centralizes the ``print + exit`` block
copy-pasted across subcommand handlers and gives callers a ``NoReturn`` type
so control-flow analysis narrows correctly after the call.
"""

from __future__ import annotations

import sys
from typing import NoReturn


def cli_error(msg: str | None = None, code: int = 1) -> NoReturn:
    """Write ``msg`` to stderr (if provided) and exit with ``code`` (default 1)."""

    if msg:
        print(msg, file=sys.stderr)
    sys.exit(code)


def cli_ok(msg: str | None = None) -> NoReturn:
    """Write ``msg`` to stdout (if provided) and exit with code 0."""

    if msg:
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
    sys.exit(0)
