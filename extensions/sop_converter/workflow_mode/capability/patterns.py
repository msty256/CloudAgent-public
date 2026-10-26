#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Known API / LLM / CLI import and call patterns for static analysis."""

from __future__ import annotations

import re

from .models import CapabilityKind

# (pattern, kind, weight)
IMPORT_PATTERNS: list[tuple[re.Pattern[str], CapabilityKind, float]] = [
    (re.compile(r"\bopenai\b", re.I), CapabilityKind.LLM_CALL, 1.0),
    (re.compile(r"\banthropic\b", re.I), CapabilityKind.LLM_CALL, 1.0),
    (re.compile(r"\blitellm\b", re.I), CapabilityKind.LLM_CALL, 1.0),
    (re.compile(r"\brequests\b", re.I), CapabilityKind.HTTP_API, 0.9),
    (re.compile(r"\bhttpx\b", re.I), CapabilityKind.HTTP_API, 0.9),
    (re.compile(r"\baiohttp\b", re.I), CapabilityKind.HTTP_API, 0.9),
    (re.compile(r"\burllib\b", re.I), CapabilityKind.HTTP_API, 0.7),
    (re.compile(r"\bsubprocess\b", re.I), CapabilityKind.EXTERNAL_CLI, 1.0),
    (re.compile(r"\bos\.system\b", re.I), CapabilityKind.EXTERNAL_CLI, 1.0),
    (re.compile(r"\bpathlib\b", re.I), CapabilityKind.FILE_IO, 0.6),
    (re.compile(r"\bshutil\b", re.I), CapabilityKind.FILE_IO, 0.8),
    (re.compile(r"\bpandas\b", re.I), CapabilityKind.DATA_PROCESSING, 0.9),
    (re.compile(r"\bnumpy\b", re.I), CapabilityKind.DATA_PROCESSING, 0.7),
    (re.compile(r"\barxiv\b", re.I), CapabilityKind.ACADEMIC_API, 1.0),
    (re.compile(r"\bduckduckgo\b|\bserpapi\b|\btavily\b", re.I), CapabilityKind.WEB_SEARCH, 1.0),
    (re.compile(r"\bexec\b|\beval\b", re.I), CapabilityKind.CODE_EXECUTION, 1.0),
]

CALL_PATTERNS: list[tuple[re.Pattern[str], CapabilityKind, float]] = [
    (
        re.compile(r"\.invoke\(|\.chat\(|ChatCompletion|messages\.create", re.I),
        CapabilityKind.LLM_CALL,
        0.9,
    ),
    (
        re.compile(r"open\(|Path\([^)]*\)\.read|\.write_text|\.read_text", re.I),
        CapabilityKind.FILE_IO,
        0.8,
    ),
    (
        re.compile(r"subprocess\.(run|call|Popen)|os\.system", re.I),
        CapabilityKind.EXTERNAL_CLI,
        1.0,
    ),
    (
        re.compile(r"requests\.(get|post|put|delete)|httpx\.(get|post)", re.I),
        CapabilityKind.HTTP_API,
        0.9,
    ),
]

FRAGILITY_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r'["\'][A-Za-z]:\\'), 0.25),
    (re.compile(r'["\']/(?:usr|home|var|tmp)/'), 0.2),
    (re.compile(r"\bsubprocess\b|\bos\.system\b"), 0.15),
    (re.compile(r"\beval\(|\bexec\("), 0.2),
]

ABSOLUTE_PATH_RE = re.compile(r'["\'][A-Za-z]:\\|["\']/[\w/]+')
