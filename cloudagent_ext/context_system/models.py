#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""
Context system data models — aligned with TypeScript CloudAgent architecture.
TypeScript references:
  -: MemoryFileInfo, MemoryType
  -: getUserContext, getSystemContext (return dict[str, str])
  -: fetchSystemPromptParts return type
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


# ---------------------------------------------------------------------------
# Memory types — mirrors MemoryType
# ---------------------------------------------------------------------------

MemoryType = Literal["Managed", "User", "Project", "Local"]

# ---------------------------------------------------------------------------
# MemoryFileInfo — mirrors MemoryFileInfo from 
# ---------------------------------------------------------------------------


@dataclass
class MemoryFileInfo:
    """A loaded memory/instruction file (CLOUDAGENT.md, rules, etc.)."""

    path: str
    type: MemoryType
    content: str
    parent: str | None = None  # Path of the file that @included this one
    globs: list[str] | None = None  # Glob patterns from frontmatter `paths:`
    content_differs_from_disk: bool = False
    raw_content: str | None = None


# ---------------------------------------------------------------------------
# SystemPromptParts — return type of fetch_system_prompt_parts()
# ---------------------------------------------------------------------------


@dataclass
class SystemPromptParts:
    """Assembled pieces for the API cache-key prefix."""

    default_system_prompt: list[str]
    user_context: dict[str, str]  # e.g. {"cloudagentMd": "...", "currentDate": "..."}
    system_context: dict[str, str]  # e.g. {"gitStatus": "..."}


# ---------------------------------------------------------------------------
# Max constants — mirrors constants
# ---------------------------------------------------------------------------

MAX_MEMORY_CHARACTER_COUNT = 40_000
MAX_STATUS_CHARS = 2_000
MAX_INCLUDE_DEPTH = 5
MEMORY_INSTRUCTION_PROMPT = (
    "Codebase and user instructions are shown below. "
    "Be sure to adhere to these instructions. "
    "IMPORTANT: These instructions OVERRIDE any default behavior "
    "and you MUST follow them exactly as written."
)

# Text file extensions allowed for @include directives (mirrors TEXT_FILE_EXTENSIONS)
TEXT_FILE_EXTENSIONS: frozenset[str] = frozenset(
    [
        ".md",
        ".txt",
        ".text",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".csv",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".mjs",
        ".cjs",
        ".mts",
        ".cts",
        ".py",
        ".pyi",
        ".pyw",
        ".rb",
        ".erb",
        ".rake",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".scala",
        ".c",
        ".cpp",
        ".cc",
        ".cxx",
        ".h",
        ".hpp",
        ".hxx",
        ".cs",
        ".swift",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".bat",
        ".cmd",
        ".env",
        ".ini",
        ".cfg",
        ".conf",
        ".config",
        ".properties",
        ".sql",
        ".graphql",
        ".gql",
        ".proto",
        ".vue",
        ".svelte",
        ".astro",
        ".ejs",
        ".hbs",
        ".pug",
        ".jade",
        ".php",
        ".pl",
        ".pm",
        ".lua",
        ".r",
        ".R",
        ".dart",
        ".ex",
        ".exs",
        ".erl",
        ".hrl",
        ".clj",
        ".cljs",
        ".cljc",
        ".edn",
        ".hs",
        ".lhs",
        ".elm",
        ".ml",
        ".mli",
        ".f",
        ".f90",
        ".f95",
        ".for",
        ".cmake",
        ".make",
        ".makefile",
        ".gradle",
        ".sbt",
        ".rst",
        ".adoc",
        ".asciidoc",
        ".org",
        ".tex",
        ".latex",
        ".lock",
        ".log",
        ".diff",
        ".patch",
    ]
)


# ---------------------------------------------------------------------------
# Legacy types — kept for backward compat with workspace_snapshot.py
# ---------------------------------------------------------------------------


@dataclass
class WorkspaceSnapshot:
    workspace_root: Path
    current_directory: Path
    top_level_entries: tuple[str, ...]
    key_files: tuple[str, ...]
    python_file_count: int
    test_file_count: int
