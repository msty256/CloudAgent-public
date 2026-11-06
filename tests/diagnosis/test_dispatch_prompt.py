#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""main 派发模式的编排约束测试。

背景（2026-11-01 `code-001` 实测）：`main` 模式的 system prompt 用的是通用
CloudAgent 提示，从没要求过委派；工具集里又有 `Read/Grep/Glob`，于是主 Agent
自己查了 40 次、只派 1 次子代理——缺口机制（注入 / decide / 域闸都在 `_agent_call`）
一次都没被触发。

这里守住的是"约束确实进了提示词"，**不是**"模型一定照做"（后者只能靠 live 观测）。
"""

from __future__ import annotations

import pytest

from cloudagent_ext.diagnosis.evaluation.executors import (
    _MAIN_DISPATCH_CONSTRAINT,
    build_main_dispatch_prompt,
)


class TestConstraintText:
    def test_covers_four_rules(self) -> None:
        text = _MAIN_DISPATCH_CONSTRAINT
        assert "取证必须委派" in text
        assert "Read / Grep / Glob 只用于理解任务" in text
        assert "不要用阅读印象代替取证" in text
        assert "作答要指出依据" in text

    def test_names_the_three_domains(self) -> None:
        for domain in ("code-diagnosis", "sql-diagnosis", "log-diagnosis"):
            assert domain in _MAIN_DISPATCH_CONSTRAINT

    def test_mentions_gap_handling(self) -> None:
        # 缺口机制是这次改造的靶心，约束里必须提到"把缺口作为下次委派目标"
        assert "缺口" in _MAIN_DISPATCH_CONSTRAINT


class TestPromptAssembly:
    def test_constraint_appended_at_end(self) -> None:
        prompt = build_main_dispatch_prompt(cwd="C:/workspace", tools=[], agents=[])
        assert _MAIN_DISPATCH_CONSTRAINT.strip() in prompt
        # 位置在末尾（长提示里，尾部指令的遵从度更稳）
        assert prompt.rstrip().endswith(_MAIN_DISPATCH_CONSTRAINT.rstrip())

    def test_prompt_is_non_trivial(self) -> None:
        """通用提示仍在（约束是追加，不是替换）。"""

        prompt = build_main_dispatch_prompt(cwd="C:/workspace", tools=[], agents=[])
        assert len(prompt) > len(_MAIN_DISPATCH_CONSTRAINT) + 1000
