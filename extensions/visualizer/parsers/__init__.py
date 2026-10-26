#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Data parsers for the Multi-Session Visualizer.

NOTE: Several parser modules (transcript_parser, tool_events_parser) have
circular imports with the builders package.  To avoid triggering those at
package-load time, only safe (non-circular) imports are listed here.
Use direct submodule imports for the others, e.g.::

    from .orchestrator_state_parser import OrchestratorStateParser

# Stats file parser kept separate to avoid circular imports.
from .stats_parser import StatsFileParser
    from .transcript_parser import TranscriptParser
    from .tool_events_parser import ToolEventsParser
"""

from .session_parser import SessionMetadataParser
from .multi_agent_parser import MultiAgentParser

# OrchestratorStateParser has no circular deps — safe to expose here.
from .orchestrator_state_parser import OrchestratorStateParser


__all__ = [
    "SessionMetadataParser",
    "MultiAgentParser",
    "OrchestratorStateParser",
]
