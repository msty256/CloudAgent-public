#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""SQL 诊断评测体系（变更 add-sql-diagnostic-evaluation-runner）。

* 消费 P2.5 案例库（``case_library``），以可重复的批量 Runner 执行诊断；
* 两种执行模式：``offline``（确定性 fixture，验证评测基础设施）与
  ``live``（真实 provider + P2.4 实际 Agent 调用链）；
* 评分器按显式口径计算六项指标并独立统计安全违规；
* 报告落盘（结构化 + 摘要 + 逐案例明细），失败案例计入分母、不被静默省略。

公共入口惰性导出（避免 ``python -m ...runner`` 时预载模块产生 runpy 警告）。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "EvaluationConfigError",
    "EvaluationError",
    "run_evaluation",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from cloudagent_ext.diagnosis.evaluation import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
