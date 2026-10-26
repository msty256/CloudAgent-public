#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Shim for pre-DECOUPLE import path ``extensions.sop_converter.composite_tools``.

Canonical implementation lives in
``extensions.sop_converter.runtime.composite_tools``.
"""

# pylint: disable=wildcard-import,unused-wildcard-import
from extensions.sop_converter.runtime.composite_tools import *  # noqa: F401, F403
from extensions.sop_converter.runtime.composite_tools import (  # noqa: F401
    _SKIP_PLACEHOLDER_COMPOSITE_TOOLS,
    _composite_to_agent_tool_spec,
    save_spec,
)
from extensions.sop_converter.runtime.composite_tools import __all__ as _runtime_all

__all__ = list(_runtime_all) + [
    "_SKIP_PLACEHOLDER_COMPOSITE_TOOLS",
    "_composite_to_agent_tool_spec",
    "save_spec",
]
