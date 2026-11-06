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

**加一个机制开关的固定流程**（P2a 起此流程由 ``SWITCHES`` 登记表落地）：

1. 在 ``SWITCHES`` 里登记（env / kind / default / off_value / off_effect）；
2. 读取点必须走 ``is_off()`` / ``current()``（或从登记表取 env 与合法值），
   不许自己裸读 ``os.environ``——``gap_injection`` 修前只认字面量 ``"off"``
   就是自己读的教训（写 ``=false`` 会静默继续注入）；
3. 在 ``tests/diagnosis/test_switch_guards.py`` 里加一条
   "关掉 ⇒ 行为消失"的用例（断言行为差异，不是断言开关读到了什么）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ENV_CONTEXT_REDUCE",
    "ENV_EVIDENCE_INVALIDATION",
    "SWITCHES",
    "SwitchSpec",
    "context_reduce_enabled",
    "current",
    "env_flag",
    "evidence_invalidation_enabled",
    "is_off",
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


# ---------------------------------------------------------------------------
# P2a：开关登记表——全部机制开关的唯一事实源
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SwitchSpec:
    """一个机制开关的登记项。"""

    name: str  # 逻辑名，如 "gap_injection"
    env: str  # 环境变量名
    kind: str  # "bool" | "mode"
    default: Any  # True/False 或 "same_target"
    modes: frozenset[str] = frozenset()  # kind=="mode" 时的合法值
    off_value: Any = None  # "关"的取值：bool→False，mode→对应档位
    #: 关掉后**应当消失**的可观察行为（人话）。守卫用例按它写，报告按它展示
    off_effect: str = ""


#: 全部机制开关。**新增开关必须在这里登记**（见模块 docstring 的三步流程）。
SWITCHES: dict[str, SwitchSpec] = {
    "context_reduce": SwitchSpec(
        name="context_reduce",
        env=ENV_CONTEXT_REDUCE,
        kind="bool",
        default=True,
        off_value=False,
        off_effect="CompressionPipeline 不再做结构归约，取证大结果原样留在上下文",
    ),
    "evidence_invalidation": SwitchSpec(
        name="evidence_invalidation",
        env=ENV_EVIDENCE_INVALIDATION,
        kind="bool",
        default=True,
        off_value=False,
        off_effect="证据冲突不再把 resolved 的缺口退回 open",
    ),
    "gap_injection": SwitchSpec(
        name="gap_injection",
        env="CLOUDAGENT_GAP_INJECTION",
        kind="bool",
        default=True,
        off_value=False,
        off_effect="子代理提示不再注入「当前有效状态」段（已确认/缺口/预算）",
    ),
    "domain_gate": SwitchSpec(
        name="domain_gate",
        env="CLOUDAGENT_DOMAIN_GATE",
        kind="mode",
        default="same_target",
        modes=frozenset({"off", "same_target", "strict"}),
        off_value="off",
        off_effect="域闸不再拦停重复委派（domain_gate 一律放行）",
    ),
    # 注意："关"不是 "off"（不在三档合法值里），而是 agent_report——
    # 那是独立核查器不运行的档位
    "goal_stop_strategy": SwitchSpec(
        name="goal_stop_strategy",
        env="CLOUDAGENT_GOAL_STOP_STRATEGY",
        kind="mode",
        default="hybrid",
        modes=frozenset({"agent_report", "transcript", "hybrid"}),
        off_value="agent_report",
        off_effect="独立核查器不运行（assessor 不触发）",
    ),
}


def current(name: str) -> Any:
    """开关当前生效值（登记表的统一读取入口）。

    mode 开关对**非法值静默回退默认**；带告警的读取（``domain_gate_mode`` /
    ``assessor_strategy``）从登记表取 env 与合法值后自行 warning。
    """

    spec = SWITCHES[name]
    if spec.kind == "bool":
        return env_flag(spec.env, spec.default)
    raw = os.environ.get(spec.env)
    if raw is None or not str(raw).strip():
        return spec.default
    text = str(raw).strip().lower()
    if text not in spec.modes:
        return spec.default
    return text


def is_off(name: str) -> bool:
    """开关当前是否处于"关"档（``off_value``）。"""

    return current(name) == SWITCHES[name].off_value


def context_reduce_enabled() -> bool:
    """阶段 3 的结构归约是否启用（默认启用）。"""

    return env_flag(ENV_CONTEXT_REDUCE, True)


def evidence_invalidation_enabled() -> bool:
    """阶段 4 的失效传播是否启用（默认启用）。"""

    return env_flag(ENV_EVIDENCE_INVALIDATION, True)
