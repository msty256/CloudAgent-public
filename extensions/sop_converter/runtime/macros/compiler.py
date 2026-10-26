#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Phase B — MacroCompiler (validate/normalize only; no LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .errors import MacroConvertError
from .session_parse import parse_session_macro_definition
from .validation import ValidatedSessionMacro, validate_session_macro_definition


@dataclass(frozen=True)
class MacroDraft:
    """Session NL/trace draft metadata; not persisted as-is."""

    proposed_name: str
    requested_scope: str = "session"
    source_steps: tuple[dict[str, Any], ...] = ()
    input_candidates: tuple[str, ...] = ()
    binding_candidates: tuple[dict[str, Any], ...] = ()
    provenance: str = "session_nl"
    diagnostics: tuple[dict[str, str], ...] = ()


def compile_macro_definition(
    data: Mapping[str, Any],
    *,
    tool_index: Iterable[str] | None = None,
    forbid_workflow_tools: Iterable[str] | None = None,
) -> ValidatedSessionMacro:
    """Strict parse + session validate — the Phase B MacroCompiler surface.

    Natural language is converted by the main Agent into ``data``; this
    function only normalizes and rejects illegal drafts.
    """
    if not isinstance(data, Mapping):
        raise MacroConvertError(
            "macro_schema_invalid",
            "definition must be a mapping",
        )
    macro = parse_session_macro_definition(dict(data))
    return validate_session_macro_definition(
        macro,
        tool_index=tool_index,
        forbid_workflow_tools=forbid_workflow_tools,
    )


__all__ = [
    "MacroDraft",
    "compile_macro_definition",
]
