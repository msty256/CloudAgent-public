#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Display layer for multi-model scheduling."""

from .bridge import MultiModelBridge
from .diff_display import DiffDisplay
from .keyboard import MultiModelKeyboard
from .protocol import DisplayPhase, ModelDisplayState, MultiModelDisplayProtocol
from .side_by_side import SideBySideDisplay
from .summary import SummaryBuilder
from .tab_display import TabbedDisplay

__all__ = [
    "DiffDisplay",
    "DisplayPhase",
    "ModelDisplayState",
    "MultiModelBridge",
    "MultiModelDisplayProtocol",
    "MultiModelKeyboard",
    "SideBySideDisplay",
    "SummaryBuilder",
    "TabbedDisplay",
]
