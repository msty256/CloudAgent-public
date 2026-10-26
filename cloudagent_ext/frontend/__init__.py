#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Downstream frontend extensions — plugin-based frontend registry."""

from cloudagent_ext.frontend.protocol import Frontend, FrontendPlugin
from cloudagent_ext.frontend.registry import get_frontend, list_frontends, register_frontend

# Import all plugins to trigger @register_frontend decorator
from cloudagent_ext.frontend import headless  # noqa: F401
from cloudagent_ext.frontend import repl  # noqa: F401
from cloudagent_ext.frontend import tui  # noqa: F401

__all__ = [
    "Frontend",
    "FrontendPlugin",
    "get_frontend",
    "list_frontends",
    "register_frontend",
]
