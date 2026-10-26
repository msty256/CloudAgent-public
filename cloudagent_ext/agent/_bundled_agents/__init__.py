#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Bundled decoupled agents.

Importing this package triggers the ``@AgentRegistry.register`` side
effect of every submodule. Callers should import it only after
``src.agent.agent_definitions`` has finished initialising.
"""

from __future__ import annotations

from cloudagent_ext.agent._bundled_agents import (  # noqa: F401
    code_diagnosis,
    code_reviewer,
    docs_writer,
    log_diagnosis,
    sql_diagnosis,
    test_runner,
)
