#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""机制开关（阶段 5 · 对照实验的底座）。

**为什么要有这一层**：对照实验的前提是"每个机制能独立开关"，
而开关必须满足两条硬要求：

1. **默认值即生产行为**——不设环境变量时行为不变，不能因为加了开关就悄悄改了默认；
2. **关了就是真的关了**——读开关的地方必须是**唯一**入口，且能被守卫用例验证。

第 2 条最容易被破坏：开关加在三个地方，其中一处忘了判断，
"关了"只是半关，对照结果就是脏的——而且从数据上完全看不出来。

**每加一个机制开关，都要同时加一条守卫用例**（`RUNNER` 侧的泄漏守卫 +
`tests/diagnosis/test_switches.py` 的语义用例）。
"""

from __future__ import annotations

import os

__all__ = [
    "ENV_CONTEXT_REDUCE",
    "ENV_EVIDENCE_INVALIDATION",
    "env_flag",
    "context_reduce_enabled",
    "evidence_invalidation_enabled",
]

#: 阶段 3：结构归约（取证大结果 → 摘要 + 句柄）。关掉 = 回到"清空/不处理"的老行为。
ENV_CONTEXT_REDUCE: str = "CLOUDAGENT_CONTEXT_REDUCE"

#: 阶段 4：证据失效传播（冲突 → resolved 退回 open）。
ENV_EVIDENCE_INVALIDATION: str = "CLOUDAGENT_EVIDENCE_INVALIDATION"

_TRUTHY = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSY = frozenset({"0", "false", "no", "off", "n", "f"})


def env_flag(name: str, default: bool) -> bool:
    """读布尔环境变量；未设置或无法识别时返回 ``default``。

    只认明确的真假写法。写成 ``"maybe"`` 这种就退回默认——**不猜**，
    因为猜错会让"我以为关了但没关"这种问题永远查不出来。
    """

    raw = os.environ.get(name)
    if raw is None:
        return default
    value = str(raw).strip().casefold()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return default


def context_reduce_enabled() -> bool:
    """阶段 3 的结构归约是否启用（默认启用）。"""

    return env_flag(ENV_CONTEXT_REDUCE, True)


def evidence_invalidation_enabled() -> bool:
    """阶段 4 的失效传播是否启用（默认启用）。"""

    return env_flag(ENV_EVIDENCE_INVALIDATION, True)
