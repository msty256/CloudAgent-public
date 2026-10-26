#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""代码分析域（P3.2 ``add-code-analysis-domain``）。

只读代码工具（``find_symbol`` / ``find_references``）与按需装配；
路径白名单 / 不执行代码 / 限额三条安全边界（不照搬 SQL 三重防线）。
"""

from __future__ import annotations

__all__: list[str] = []
