#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Persistent Plan Graph extension for CloudAgent.

Runtime integrations import the focused submodules directly.  Keeping the
package root intentionally empty prevents importing retired sidecar, solver,
and decomposition implementations as a side effect of ``import lkb``.
"""

__all__: list[str] = []
