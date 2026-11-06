# 阶段 1 提案：停止判定 + 域维度

> 对应总纲 [`diagnosis-redesign.md`](../diagnosis-redesign.md) §4.1（第二、三小步）与 §5「阶段 1」
> 前置：阶段 0（度量地基）已确认；A1（协议 + 评估器链）已在起点提交前完成
> 状态：**三个决策点已定（2026-10-29，均按推荐）；T1.1–T1.6 已实现（2026-10-31）**
> 提案日期：2026-10-29 ｜ 决策更新：2026-10-29 ｜ 执行：2026-10-31（见 §12）

---

## 0. 一句话目标

让"**这个域卡住了**"这句话第一次产生行为：拦掉**同一个问法死磕**的派发，
并让模型看到结构化的拦截原因而不是一句异常；同时把"某域配额用尽"从异常改成可归因的判定。

## 1. 起点：A1 留下了什么，本阶段要补什么

### 1.1 已完成（回顾，避免重复实现）

`decide()` 已从五条 if-else 改成评估器链 + 确定性折叠，五个评估器：

```
budget_exhausted(hard) → gap_open → blocked_only → success_recorded → budget_available(兜底)
```

`blocked_only` 现在**能算出来**了（`reason="blocked_only"`），但——**它仍然不产生任何行为**。
`_agent_call`（`agent.py:720-721`）只对 `budget_exhausted` 硬停，其余一律 `logger.debug`。

所以本阶段的第一件事不是"再造一个判定"，而是**给已有的判定接上出口**。

### 1.2 本阶段要补的三件事

| # | 缺什么 | 位置 |
|---|---|---|
| 1 | 缺口没有"来自哪个域" | `Gap`（`models.py:601`）无 `source_domain`；`gap_summary()`（`runtime_session.py:115`）是会话级快照 |
| 2 | 域级判定没有出口 | `blocked_only` 只进 debug 日志 |
| 3 | 配额耗尽以异常形式出现 | 域配额 = 现有的 `max_delegations_per_agent`，检查在 `session.py:175` 与 `runtime_session.py:296`，**抛 `DiagnosisSessionError`** |

---

## 2. 两个必须先讲清的设计问题

### 2.1 折叠产出的是"单一决策"，而域维度天然需要两个独立判定

A1 的 `EvaluatorChain.evaluate()` 返回**一个** `StopDecision`，`decide()` 拿它转成 `SessionDecision`。
如果直接把"域配额"这类评估器塞进同一条链，会出问题：

`decision_tier()` 的实现是 `hard → 0`（最高优先）。域配额按论文语义属于 `g_cap`（硬上限），
于是它会赢得折叠 → `decide()` 返回 `stop` → **整个会话停了**。
但域配额的语义是"**这个域别再派了**"，其他域（log / sql）应该照常。

**解决办法：按 scope 拆成两条链，各自折叠。**

```python
# diagnosis/evaluators.py
def build_session_chain() -> EvaluatorChain[DiagnosisStopContext]   # 现有五个，不动
def build_domain_chain()  -> EvaluatorChain[DiagnosisStopContext]   # 新增：域级两个
```

| 链 | 谁调 | 输入 | 输出 | 消费者 |
|---|---|---|---|---|
| 会话链 | `InvestigationSession.decide()` | 会话级快照 | `SessionDecision`（兼容现有契约） | `runtime.decide()` → `_agent_call` 的硬停判断 |
| 域链 | `runtime.domain_gate(domain)` | 会话快照 + 该域缺口 | 原样返回 `StopDecision`（协议对象） | `_agent_call` 的派发前域闸 |

**为什么域链直接返回协议对象而不复用 `SessionDecision`**：`SessionDecision` 是老接口，
有既有消费者（`_diagnosis_stopped_result` 读 `decision.reason`）。域级判定只有新消费者，
直接用协议对象可以带 `domain` / `scope`，不必给老 dataclass 加字段。

**对 A1 的影响**：零。会话链的评估器与注册序都不变，`test_stop_decision.py` 的 36 组等价性用例继续有效。

### 2.2 "按域配额"其实已经存在，A3 的增量是换出口

这点必须写在前面，否则会重复实现一遍。

现有 `SessionBudget.max_delegations_per_agent = 5`（env 可配），检查点在两处：

- `session.py:164-169`：诊断委派，`agent_used = sum(1 for entry in entries if entry.task.agent_type == agent_type)`
- `runtime_session.py:287-301`：非诊断委派，`other_delegations[agent_type]`

而 `agent_type` 就是域（`sql-diagnosis` / `log-diagnosis` / `code-diagnosis`）。
**所以"每个域最多派几次"这个限制一直都在**，只是：

1. 它以**抛异常**的形式出现（`DiagnosisSessionError` → `_agent_call` 转 `ToolInputError`），
   模型看到的是"工具调用参数错误"式的文本，**没有该域缺口清单、没有"换个域"的提示**；
2. 它在决策统计里**不可见**——`decision_counts` 里不会出现"域配额"这个原因。

所以 A3 做的事是：

- **保留** `delegate()` 里的硬检查（它是防绕过的最终防线，不能删）；
- **新增**链上的域配额评估器作为**派发前预判**：命中时返回结构化 tool_result，
  告诉模型"该域配额已用尽，建议换域或基于现有证据作答"，而不是抛异常。

区别的实际效果：抛异常时模型可能以为参数写错了去重试；tool_result 明确指向"换域"。

**域配额默认值的问题**：如果域配额 = `max_delegations_per_agent` = 5，
那 A3 只是"同一个数字换个出口"，不会更早掐死单域。要不要让域配额**小于** per-agent 上限
（比如 3），是个决策点（见 §6 决策点 2）。

---

## 3. 任务步骤

### T1.1 缺口带上来源域

**做什么**

1. `Gap` 增加 `source_domain: str = ""`（默认空，向后兼容；`Gap` 全仓只有
   `runtime_session.py:403` 一处构造，影响面极小）；
2. `harvest_gaps(runtime, parsed, *, domain="")` 增加关键字参数——**必须带默认值**，
   因为 `tests/diagnosis/test_gap_orchestration.py` 里有 10 处两参调用；
3. `finish_delegation` 调用时传 `domain=task.agent_type`（原料现成：`InvestigationTask.agent_type`）；
4. 域标识归一：存**原始 agent_type**（`code-diagnosis`），另提供
   `domain_of(agent_type) -> "code"` 的纯函数（去掉 `-diagnosis` 后缀，非诊断返回原值），
   展示与判定都用短名，存储保留原值以便追溯；
5. `gap_summary(domain: str | None = None)` 支持按域过滤：`None` = 全量（现有行为），
   传域则只统计该域的缺口。

**验收**：新增用例——两个域的委派各产缺口，`gap_summary("code")` 只看到 code 的；
既有 10 处 `harvest_gaps(rt, result)` 调用零改动仍通过。

### T1.2 域级判定的纯函数（先不接链）

**做什么**

新增 `cloudagent_ext/diagnosis/domain_gate.py`，两个纯函数 + 两个评估器类：

```python
def domain_progress(objective, domain_gaps, *, mode) -> StopDecision | None
# mode ∈ {"off", "strict", "same_target"}
# 返回 None 表示放行

def domain_quota(domain, budget_view) -> StopDecision | None
```

**"同目标"判据（推荐方案的精确实现）**

```
对每条 status ∈ {blocked, inconclusive} 的该域缺口：
    取其关键词 kws = extract_keywords(gap.statement)
    若 kws 非空 且 contains_all(objective, kws, normalize=True) → 拦
理由写进 decision.reason：f"domain_blocked:{gap_id}"
```

为什么是"缺口关键词全部出现在 objective 里"而不是反过来：
- 反方向（objective 被缺口覆盖）几乎永不成立——objective 通常更长、更具体；
- 交集判据太松——objective 里顺带提了一个词就拦，会误伤正常的多目标派发。

**`inconclusive` 也要判**：它表示"复述多次仍无进展"，同一问法再派大概率还是无进展。
注意这与 `GapSummary.only_blocked` 的口径一致（那里也把 blocked + inconclusive 都算"不可继续"）。

**验收**：纯函数单测，表驱动覆盖三种 mode × 四种缺口状态组合；不涉及任何 I/O。

### T1.3 接进域链 + 派发前拦截

**做什么**

1. `runtime.domain_gate(domain) -> StopDecision | None`：构造域上下文（会话快照 + 该域缺口 + 配额），
   跑 `build_domain_chain()`；
2. `_agent_call` 在 `runtime.decide()` **之后**、`begin_delegation` **之前**加一步：
   诊断类委派先查域闸，命中则直接返回结构化 tool_result（**不记账**，因为没派出去）；
3. 结构化返回值复用 `_diagnosis_stopped_result` 的渲染逻辑（抽一个带 `domain` 参数的变体，
   **不要复制第二份渲染代码**），payload 形状：

```python
{
  "status": "error",           # _map_result_to_api 只认这三个键，缺了模型侧收到空结果
  "error": "<人读文本：哪个域、为什么、几条缺口重叠、建议换哪个域>",
  "error_type": "DomainGated",
  "reason": "domain_blocked" | "domain_quota_exhausted",
  "domain": "code",
  "gaps": [...该域缺口...],
  "entries": [...该域已有委派...],
  "note": "该域已被域闸拦下：请换一个域取证，或基于现有证据直接作答。",
}
```

**顺序很重要**：域闸在 `begin_delegation` 之前 → 被拦的派发不消耗预算。
这与现有"派发失败仍记账（防绕过）"的设计**不冲突**：那条针对的是"派发已经发生但结果失败"，
而域闸是"根本没发出去"。

**验收**：多域用例——code 域被拦时，同一会话里派 log 域仍然成功且 `delegations_used` 只加 1。

### T1.4 `/tasks` 按域分组

**做什么**

`command_system/tasks_command.py:61-75` 现在把所有缺口平铺。改为：
有 `source_domain` 时按域分组显示，并在该域被闸拦过时加一行标记。

```
缺口：
  [code]  1 open / 2 blocked
    • [blocked] 缺 Kafka 消费位点权限（复述 1 次）
  [log]   1 open
    • [open] 核对 orders 表 order-1 是否写入（复述 0 次）
域闸：code 被拦 1 次（domain_blocked:gap-2）
```

**为什么放在这个阶段**：这是"人看的视图"与"Agent 用的状态"同一份数据的最小验证
（Runtime 优化指南第 7 条）。改动小，但能立刻看出域维度是否真的落地了。

**验收**：渲染函数单测（纯字符串，无需真实会话）。

### T1.5 测试与回归

**做什么**

| 类型 | 内容 |
|---|---|
| 新增 | `tests/diagnosis/test_domain_gate.py`：同目标判据、严格模式、配额、非诊断委派、多域不误伤 |
| 新增 | 多域集成用例（照 `test_gap_orchestration.py::TestDispatchPolicy` 的风格，走真实 `Agent` 工具） |
| 回归 | `test_gap_orchestration.py` / `test_session.py` / `test_stop_decision.py` 必须全绿；**`test_blocked_only_is_advisory` 按选定 mode 处理**（见 §6 决策点 1） |

### T1.6 配额配置化

**做什么**

- 新增 `CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS`（默认值见决策点 2），走
  `runtime_session._read_limit()` 同一套解析与上限校验（不新写一套）；
- 三档默认：`off`（不启用域闸，等价现状）/ `same_target`（推荐）/ `strict`，
  用 `CLOUDAGENT_DOMAIN_GATE` 选，便于阶段 5 分臂。

**验收**：环境变量非法值回退默认并告警（照 `_read_limit` 现有行为）；三档切换各有一条用例。

---

## 4. 产出物

| 类型 | 路径 | 说明 |
|---|---|---|
| 代码 | `diagnosis/models.py` | `Gap.source_domain` |
| 代码 | `diagnosis/runtime_session.py` | 收割传域、`gap_summary(domain)`、`domain_gate()`、配额配置 |
| 代码 | `diagnosis/domain_gate.py`（新） | 域级判定的纯函数 + 评估器 |
| 代码 | `diagnosis/evaluators.py` | `build_domain_chain()`；会话链不动 |
| 代码 | `tool_system/tools/agent.py` | 派发前域闸 + 结构化返回值变体 |
| 代码 | `command_system/tasks_command.py` | 按域分组渲染 |
| 测试 | `tests/diagnosis/test_domain_gate.py`（新） | 判据 + 配额 + 多域不误伤 |
| 文档 | 总纲 §4.1 状态更新 | A2/A3 从"待做"改为"已完成"，并记录最终选定的 mode |

## 5. 依赖关系

**前置**：阶段 0 的 T0.3（`decision_counts`）——否则"域闸拦了几次""误停止率"都统计不到。

**本阶段内部**：T1.1 → T1.2 → T1.3 → T1.6 →（并行）T1.4 / T1.5。

**被谁依赖**：

| 后续阶段 | 依赖什么 |
|---|---|
| 阶段 2（状态可信） | `source_domain`（状态段要按域展示"该域已确认什么"） |
| 阶段 4（证据失效传播） | 域归因（回退要定位到域，才能只重派该域） |
| 阶段 5（对照实验） | 三档 mode 开关（域闸本身就是一个实验变量） |

## 6. 决策点（三个，需要你定）

### 决策点 1：域闸用哪种规则

| 选项 | 规则 | 对现有测试的影响 |
|---|---|---|
| (a) `strict` | 该域没有 open 缺口、只有 blocked/inconclusive → 拦该域**一切**派发 | **必须改** `test_blocked_only_is_advisory`（它断言同域换目标再派要放行） |
| **(b) `same_target`（推荐）** | 只在"objective 覆盖某条 blocked/inconclusive 缺口的关键词"时拦 | **零改动**：现有用例的目标与缺口无关键词交集 |
| (c) `off` | 只做域归因 + 配额，不做 blocked 拦截 | 零改动，但 `blocked_only` 仍是死路径 |

推荐 (b) 的依据：论文的 `Φ=blocked` 是**任务级**判定，我们是**域级**，粒度更细；
"blocked"意味着"这个问法推进不了"，不是"这个域死了"。同目标拦截恰是这个语义的最小落地。

保留 `strict` 与 `off` 两档的意义：它们是阶段 5 的实验变量（对照"拦得松/紧"的差别），
不是备选实现——**三档都要实现，只是默认值选哪个**。

> **已定（2026-10-29）：默认 `same_target`，三档全部实现。**
> `CLOUDAGENT_DOMAIN_GATE = off | same_target | strict`，缺省 `same_target`。


### 决策点 2：域配额的默认值

现状 `max_delegations_per_agent = 5`（env 可配）。三个选择：

| 选项 | 效果 |
|---|---|
| (a) 域配额 = per-agent 上限（5） | 只是换个出口，不会更早掐死单域 |
| **(b) 域配额 = 3（推荐）** | 单域最多 3 次就转向，per-agent 的 5 仍是硬兜底；多域流程不受影响 |
| (c) 不设域配额，只做 blocked 拦截 | A3 实际不落地，等有数据再定 |

推荐 (b) 的理由：`code` 域一共 7 道题，单域派 5 次以上几乎没有新信息；
但**这个数字必须有据可依**——阶段 0 的基线会给出"每结论平均委派数"，若基线显示常态是 4–5 次，
那 3 就太紧，应回到 5。**所以 (b) 的数值在阶段 0 基线出来后再最终敲定**，本阶段先按 3 实现、可配。

> **已定（2026-10-29）：默认 3，可配；等阶段 0 基线出来复核一次。**
> `CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS`，缺省 3；`max_delegations_per_agent`（5）保留为硬兜底。


### 决策点 3：域闸被拦时是否消耗预算

| 选项 | 说明 |
|---|---|
| **(a) 不消耗（推荐）** | 闸在 `begin_delegation` 之前，没派出去就不记账；模型可以换域继续 |
| (b) 消耗 | 与"派发失败仍记账"的防绕过逻辑一致，但会惩罚"试探性派发" |

推荐 (a)：防绕过针对的是"派发出去了但结果失败"，域闸是"根本没发出去"，
两者不是一类事。且若消耗，模型在一个卡住的域上试探几次就会把全局预算烧光。

> **已定（2026-10-29）：不消耗预算。** 域闸位于 `begin_delegation` 之前，被拦的派发不记账。


## 7. 风险与应对

| 风险 | 表现 | 应对 |
|---|---|---|
| 域闸误伤多域流程 | 一个域卡住导致其他域也派不出去 | 域链与会话链分离（§2.1）；多域用例专门守这条 |
| 同目标判据把正常派发判成死磕 | objective 里恰好提到缺口关键词 | 判据要求**缺口关键词全部出现**；三档可切，先跑 `same_target` 观察拦截率 |
| `source_domain` 为空的历史缺口 | 老会话的缺口没有域，域闸判不了 | 空域缺口归入"未归因"，域闸跳过它们（不拦），并在 `/tasks` 里单列 |
| 域配额与 per-agent 上限重复 | 两个数字，容易混淆 | 文档写清：per-agent = 硬兜底（抛异常），域配额 = 派发前预判（tool_result）；默认值不同 |
| 结构化 tool_result 缺 `status`/`error` | 模型侧收到空结果（历史踩过） | 复用 `_diagnosis_stopped_result` 的渲染逻辑，不新写；用例断言两个键存在 |
| 埋点/接线引入回归 | 改了 `_agent_call` 的控制流 | 域闸插在 decide 之后、begin_delegation 之前，失败一律放行（异常不得阻断派发） |
| 三档 mode 增加组合复杂度 | 测试组合爆炸 | 表驱动，只测三档 × 关键状态；不测笛卡尔积 |

## 8. 工作量与顺序

| 步 | 规模 | 依赖 live | 备注 |
|---|---|---|---|
| T1.1 域归因 | 小 | 否 | 改 1 个 dataclass + 1 个函数签名 |
| T1.2 纯函数 | 小 | 否 | 判据最需要想清楚，其余是样板 |
| T1.3 接线 | 中 | 否 | 唯一碰到 `_agent_call` 的地方，最需要小心 |
| T1.6 配置 | 小 | 否 | 复用 `_read_limit` |
| T1.4 `/tasks` | 小 | 否 | 纯渲染 |
| T1.5 测试 | 中 | 否 | 多域集成用例是重点 |

**不需要跑 live**：本阶段全部可用离线 stub + 单测验证。live 只在阶段 0 的基线与阶段 5 的对照里用。

建议顺序：T1.1 → T1.2 → T1.3 → T1.6 → T1.4 → T1.5（最后统一跑一次全量回归）。

## 9. 完成的标准（本阶段出口）

能同时回答这三个问题，本阶段才算完：

1. **为什么没派出去？** —— 模型收到的 tool_result 里有域名、原因、该域缺口、换域建议；
2. **是不是误伤？** —— 多域用例证明：一个域被拦时，其他域照常，`delegations_used` 只增 1；
3. **拦了多少次？** —— 阶段 0 的 `decision_counts` 里能看到 `domain_blocked` / `domain_quota_exhausted`。

至于"拦得对不对"（拦截是否提高诊断质量）——**不在本阶段回答**，那是阶段 5 的对照实验。

---

## 10. 决策记录

| 时间 | 决策 | 影响 |
|---|---|---|
| 2026-10-29 | 域闸默认 `same_target`；`off` / `strict` 也实现 | 现有 `test_blocked_only_is_advisory` **零改动**；三档成为阶段 5 的实验变量 |
| 2026-10-29 | 域配额默认 3（可配），`max_delegations_per_agent=5` 保留为硬兜底 | T1.6 新增 env；等阶段 0 基线的"每结论平均委派数"复核这个数值 |
| 2026-10-29 | 域闸被拦**不消耗预算** | T1.3 的插入位置固定在 `begin_delegation` 之前 |

---

## 12. 执行记录（2026-10-31）

### 12.1 交付清单

| 步 | 交付 | 位置 |
|---|---|---|
| T1.1 | `Gap.source_domain`（默认空）；`harvest_gaps(..., domain="")`；`gap_summary(domain=None)`；`domain_of()` 把 `code-diagnosis` 归成 `code` | `models.py` / `runtime_session.py` / `domain_gate.py` |
| T1.1 补充 | **再收割时回填**：老缺口（无域）下次被同一命题命中就补上归因，避免永远"未归因" | `runtime_session.py::harvest_gaps` |
| T1.2 | `domain_gate.py`：`DomainGateContext` + `DomainQuotaEvaluator` + `BlockedDomainEvaluator` + `build_domain_chain()`；纯函数、无 I/O | `diagnosis/domain_gate.py`（新） |
| T1.3 | `runtime.domain_gate(domain, objective)` 走**独立域链**；`_agent_call` 在 `decide()` 之后、`begin_delegation` 之前查闸；命中返回 `error_type="DomainGated"` 的结构化 tool_result | `runtime_session.py` / `agent.py` |
| T1.3 补充 | 抽出 `_gap_records()` / `_entry_records()`，会话终止与域拦截共用一份序列化（不复制第二份渲染逻辑）；`_domain_gated_result()` 额外给 `domain` / `suggested_alternatives` | `agent.py` |
| T1.6 | `CLOUDAGENT_DOMAIN_GATE`（默认 `same_target`，非法值告警回退）/ `CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS`（默认 3，**`0` = 关配额**） | `runtime_session.py` |
| T1.4 | `/tasks` 缺口按域分组（**无任何域归因时保持原平铺格式**，老数据不受影响）；新增"域闸拦截：code 1 次"一行 | `tasks_command.py` |
| T1.5 | `test_domain_gate.py`（29 用例）：三档判据、配额、归因/回填、配置、多域集成不误伤 | `tests/diagnosis/` |

### 12.2 与提案的两处偏差

**① `build_domain_chain()` 放在 `domain_gate.py`，不在 `evaluators.py`。**
提案写的是 `evaluators.build_domain_chain()`。实际把域相关的上下文、评估器、链都放在同一个模块，
理由是它们共用 `DomainGateContext` 且与会话链无关；`evaluators.py` 保持"会话级五个评估器"这一件事。
分层上没有区别（两者都在 `diagnosis/` 领域层）。

**② 配额用 `0` 表示"关闭"，没有单开一个开关。**
原因：阶段 5 要跑 `arm:budget`（只开配额）与 `baseline`（全关），需要两者能独立控制。
用 `0` 当哨兵值比再加一个 env 简单，且在 `default_domain_quota()` 里显式短路，不会落到 `_read_limit` 的告警分支。

### 12.3 验证结果

```
tests/diagnosis/test_domain_gate.py           29 passed   ← 新增
tests/diagnosis/（全量）             649 passed, 25 skipped   （阶段 0 后是 620）
```

关键验证点：

- `test_blocked_only_is_advisory`（同域换目标再派**必须放行**）**零改动通过**——
  因为 `same_target` 判据要求"objective 覆盖缺口全部关键词"，而它的目标是"查 B"、缺口关键词是 `kafka`；
- 多域集成用例：code 域被拦时 `delegations_used` 不变（不消耗预算），log 域照常派发且只加 1；
- `gate=off` 时行为回到改造前（`domain_blocks == {}`）。

**环境说明**：`tests/tool_system/` 有 30 个用例失败，原因是 `extensions/lkb/src/lkb/file_lock.py:89`
import `winerror`（pywin32 未装），与本次改动无关（本次只动 `diagnosis/`、`command_system/tasks_command.py`）。


