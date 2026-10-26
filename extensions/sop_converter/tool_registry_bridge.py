#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.runtime import tool_registry_bridge as _impl
import sys

# Prefer the runtime module for subsequent ``import`` lookups.
sys.modules[__name__] = _impl
# When this file is ``importlib``-exec'd into a pre-created module object,
# that object is what callers hold onto — mirror public names onto it too.
globals().update(
    {k: v for k, v in vars(_impl).items() if k not in ("__name__", "__file__", "__package__", "__loader__", "__spec__")}
)
