# 阶段 5 提案：对照实验

> 对应总纲 [`diagnosis-redesign.md`](../diagnosis-redesign.md) §6 与 §5「阶段 5」
> 前置：阶段 0（度量）、1（域维度）、2（状态可信）、3（上下文）、4（失效传播）
> 状态：**待确认**（本文只是提案，未动任何代码）
> 提案日期：2026-10-30

---

## 0. 一句话目标

把前四个阶段引入的每个机制变成**一个可独立开关的实验臂**，跑出「谁起了作用、起了多大作用」，
并且能区分**机制保证的效果**与**统计上说得出口的效果**——后者很可能一个都没有。

## 1. 起点：现有实验设施能用到什么程度

> **⚠ 阻塞项（2026-11-01 首次 live 实测发现）**：`main` 模式下评分器拿不到可解析结果。
> `LiveExecutor` 的 `raw_output` 取的是 `result.response_text`——在 `main` 派发时那是
> **主 Agent 的散文回复**；而 `score_case` 要求诊断协议 JSON（`request_id` / `evidence` / …）。
> 实测 `code-001`：`counts = {parsed: 0, invalid_output: 1}`，于是 top1 与 evidence 均为 0%。
>
> **同一次实测还暴露了更前置的问题（P1，已修）**：主 Agent 30 轮打满、40 次自己的工具调用、
> 只派 1 次子代理——因为 `main` 模式的 system prompt 是通用那套，**从没要求过委派**，
> 而工具集里同时给了 `Read/Grep/Glob`。结果是缺口机制（注入 / decide / 域闸都在 `_agent_call`）
> **一次都没被触发**，`main` 模式退化成"更贵的 direct"。
> 已按方案 a 修复：`executors._MAIN_DISPATCH_CONSTRAINT` 追加到系统提示末尾
> （只加约束、不删工具，保留 `Read` 用于理解任务）。**这一点必须重跑验证才算数。**
>
> 剩下的是 P2（评分对象）：**已按方案 (c) 修复（2026-11-01）**——
> `--grade-source {auto,main,subagent}`，`auto`（默认）在 `main` 派发下取
> **最后一个诊断子代理的协议结果**（来自会话账本 `entry.result`，不经主 Agent 转述）；
> 主 Agent 的原始回答保留在 `case.main_answer`，不丢信息。
> 生效值写进 `run.json.grade_source` 与每个 case 的 `meta.grade_source`。
> **注意**：这意味着 `main` 模式评的是"子代理结论对不对"，而不是"主 Agent 转述得准不准"——
> 后者要用 `--grade-source main` 单独看。两件事不要混在一个指标里。
>
> 备选方案记录（已选 c，另两个不采用）：
>
> | 方案 | 做法 | 为什么不选 |
> |---|---|---|
> | (a) 取被委派方的结果 | 从 `events` / `calls` 里定位最后一次子代理的协议 JSON | 与 c 实际同效，但把"取谁"写死在代码里，不能显式对比 |
> | (b) 让主 Agent 输出契约 | 在 main 系统提示里要求最终以 JSON 收尾 | 改的是被测行为，会污染对照 |
>
> 推荐 (c)：既不改语义，也不改提示，把口径变成显式参数；阶段 5 的每一臂都要记录这个参数。

### 1.1 已经有的

| 设施 | 位置 | 现状 |
|---|---|---|
| 分臂参数 | `--variant gaps-on\|gaps-off` | **只有二值** |
| 开关泄漏守卫 | `runner.py:350-352` | 只守 `gaps-off` 臂的 `injected_dispatches > 0` |
| 跨轮聚合 | `_experiment_stats` | 阶段 0 的 T0.5 修过 repeat |
| 对比报告 | `_compare_runs` | 产 md，含"不构成对照结论"的标注 |
| 逐 case 明细 | `results[]` | 含 `raw_output` / `meta` / `calls` / `events` |

### 1.2 缺的

0. **case 集体检（新增，阻断级）**：2026-11-01 发现 `code-007` 的 `ground_truth` 描述的是**旧行为**
   （"`is_async` 为真时提前 return，异步拿不到校验块"），而该问题已被 `wire-investigation-session`
   修掉（`agent.py:1877-1879` 注释自述）。子代理判断正确、评分判错，于是 Top-1 = 0。
   → **已做全 5 域体检（38 题）**：仅 **15 题可静态核实**，其中 **3 题过期**；
   另 **23 题（61%）无法核实**（sql 14 缺 seed、cross 6 描述外部 Java 项目、sync 3 缺 orders/日志）。
   详见 [`case-audit-2026-11-01.md`](../case-audit-2026-11-01.md)。
   → **任何对照之前，先把过期题改掉或删掉**；改 gt 必须人工对着代码改并写明依据，
   **不能拿模型答案当标准答案**（那是用被测对象定义正确性）。
   → 统计正确率时**只算 `verification ∈ {static, runtime}` 的题**，`external` 的题单列。
1. **多臂表达**：五个机制要各自可开关，而 `variant` 是二值枚举；
2. **守卫要泛化**：每个开关都需要"声明关了，就验证真的关了"；
3. **"误停止率"没有定义**，也没算过；
4. **结论级抽查没有载体**：评分打的是字段匹配分，看不出"结论本身对不对"。

### 1.3 一个必须承认的限制：A1 没有臂

A1（停止决策协议 + 评估器链）是**等价重构**，没有开关、也不该有。
所以 §8 原稿里的"Baseline / A"两臂其实**不存在**——它们行为必须相同。

这既是限制也是验证手段：如果将来有人给 A1 加了开关并跑出差异，那说明等价性有 bug。
**本阶段不设 A 臂**，A1 的正确性由 `test_stop_decision.py` 的 36 组等价性用例背书（离线、可重复、成本为零），
不靠 live 对比。

---

## 2. 三个必须先讲清的设计问题

### 2.0 成本上限（2026-11-01 实测后新增，**先于其他一切**）
单例实测（`code-007`，main 派发）：**输入 326 万 token / 350 秒**。`code-001` 是 143 万 / 124 秒。

按这个数字回推原方案：

| 方案 | 用例数 | 臂数 | 轮数 | 预计输入 token |
|---|---|---|---|---|
| 原稿 | 7 | 5 | 2 | **≈ 1.1 亿** |
| 收缩后（只跑 3 例 × 4 臂 × 1 轮） | 3 | 4 | 1 | ≈ 3900 万 |

结论：**原稿的规模不可能执行**。三条压缩路径（可叠加）：

1. **减例**：机制验证只需 2–3 例（`code-007` 能产出 12 条缺口，已足够暴露机制行为）；
2. **减臂**：`baseline` / `arm:state` / `arm:inval` 三臂即可覆盖主要变量，域闸两臂可延后；
3. **减轮**：`--repeat` 只在对"随机性"有结论需求时开，机制类指标单轮即可。

另外两条**降低成本的结构性**手段（不影响对照有效性）：

- 系统提示 25k 字符 × 77 次调用是主要成本来源，压缩它是"阶段 3 的活"，
  但阶段 3 的收益要在**这里**才看得见——所以阶段 3 应先于阶段 5；
- 该端点不返回 cache 字段，没有缓存折扣；若换支持 prompt caching 的端点，成本可显著下降
  （这也是"等阶段 0 测单价"的真正含义）。

### 2.1 臂怎么表达：开关独立，variant 只是预设

不要扩 `variant` 枚举来表达机制组合（组合会爆炸，且守卫难写）。改成：

**底层是一组独立环境变量**（每个机制一个），`variant` 只做"预设组合"的语法糖：

| 开关 | 取值 | 引入阶段 | 语义 |
|---|---|---|---|
| `CLOUDAGENT_GAP_INJECTION` | `on` / `off` | 既有 | 缺口注入 |
| `CLOUDAGENT_DOMAIN_GATE` | `off` / `same_target` / `strict` | 阶段 1 | 域闸 |
| `CLOUDAGENT_DIAGNOSIS_DOMAIN_MAX_DELEGATIONS` | 整数 | 阶段 1 | 域配额 |
| `CLOUDAGENT_GOAL_STOP_STRATEGY` | `agent_report` / `transcript` / `hybrid` | 阶段 2 | 独立核查 |
| `CLOUDAGENT_EVIDENCE_INVALIDATION` | `on` / `off` | 阶段 4 | 失效传播 |
| `CLOUDAGENT_CONTEXT_REDUCE` | `on` / `off` | 阶段 3 | 结构归约 |

臂 = 一组取值。一期只跑**单变量臂**（相对 baseline 只改一个开关），这样差异可以归因。

```
baseline      injection=on   gate=off     strategy=agent_report  invalidation=off  reduce=off
arm:domain    injection=on   gate=same_target  strategy=agent_report  invalidation=off  reduce=off
arm:budget    injection=on   gate=off     domain_max=3  strategy=agent_report  invalidation=off  reduce=off
arm:state     injection=on   gate=off     strategy=hybrid  invalidation=off  reduce=off
arm:inval     injection=on   gate=off     strategy=agent_report  invalidation=on  reduce=off
```

注意 `arm:inval` 的依赖：失效传播要求"回退后再 resolved 须过核查"，而核查在 `agent_report`
档下不工作。所以 `arm:inval` 实际需要 `strategy=hybrid`——**它不是严格的单变量臂**。
这个矛盾在 §6 决策点 1 里给出两种处理方式。

### 2.2 "误停止率"的精确定义

这个词很容易被误解成"系统提前结束导致失败"。我们有两种可算的口径，含义不同：

**口径 A（编排层误判率）**：`decide()` 返回 stop 的次数中，**当时该 case 的
`required_evidence` 尚未覆盖**的比例。

- 可精确计算：`decide().reason` 已有（阶段 0 的 T0.3），`evidence_sufficient` 是评分已有字段；
- 它衡量的是"**编排层的判断对不对**"，与主 Agent 是否听从无关。

**口径 B（结果层过早收敛）**：相对 baseline，`delegations` 更少且 `top1_hit` 从命中变未命中的 case 数。

- 它衡量的是"**实际后果**"，但受模型随机性影响大，7 例里可能只有 1–2 例能观察到。

**推荐两个都报**，但结论只挂在口径 A 上——因为口径 B 在样本量 7 的情况下不足以支撑任何断言。

### 2.3 结论级抽查：不是打分，是核对业务结论

HLD 帖的教训是"字段齐全、计算自洽、结论仍错"。评分器打的是
`root_causes[].match_terms` 命中率，**命中词不等于结论对**。

抽查载体：每条臂产出一张 markdown 表，人工逐行判定。

```markdown
| case | 臂 | 系统结论（摘要） | ground_truth 要点 | 判定 | 备注 |
|---|---|---|---|---|---|
| code-001 | baseline | "SessionBudget 在 _agent_call 生效…" | 派发链路确实经过 InvestigationSession | ✅ | — |
| code-003 | arm:state | "…" | … | ⚠️ | 引用了不存在的函数名 |
```

判定三档：✅ 结论正确 / ⚠️ 部分正确或有事实错误 / ❌ 结论错误。

**人工为主，LLM 只做预筛**：可以用 B2 的 assessor 帮助标记"结论与 ground_truth 直接矛盾"的行，
但**判定列必须人工填**——否则又是一次"用模型判模型"。

规模：7 例 × 5 臂 = 35 条。这就是为什么基线只取 code 域（阶段 0 的决策）。

---

## 3. 任务步骤

### T5.1 开关注册表（单一事实源）

**做什么**

新增 `cloudagent_ext/diagnosis/evaluation/arms.py`：

```python
ARMS: dict[str, dict[str, str]]   # 臂名 → {env_var: value}
def apply_arm(name: str) -> contextmanager   # 进臂设 env，出臂还原（照 gaps-off 的现有做法）
def effective_flags() -> dict[str, str]      # 当前实际生效的开关值（写进 payload）
def assert_arm_effective(payload, arm_name) -> list[str]   # 守卫：返回违规列表
```

守卫要**逐开关**，不是只守注入：

| 臂 | 守卫断言 |
|---|---|
| `baseline` | `injected_dispatches > 0`（注入确实开了）；`gate_hits == 0`；`assessments == 0`；`gap_reverts == 0` |
| `arm:domain` | `gate_hits > 0` 或明确记 `gate_never_triggered`；其余为零 |
| `arm:budget` | 同上 + 配额命中计数 |
| `arm:state` | `assessments > 0`（核查确实跑了）；`gap_reverts == 0` |
| `arm:inval` | `gap_reverts > 0` 或记 `invalidation_never_triggered` |

"未触发"不等于"违规"——一个臂可能在这批 case 上本来就触发不到。所以守卫分两级：
**违规**（声明关了却出现了效果）必须 fail；**未触发**只 warn 并写进报告。

### T5.2 `--arm` 参数

**做什么**

`runner.py` 新增 `--arm NAME`（可重复），与现有 `--variant` 共存：

- `--variant gaps-on|gaps-off` 保留，等价于 `arm:injection-on|injection-off`（向后兼容旧命令）；
- `--arm` 与 `--variant` 同时出现 → 报错（避免"名义分臂、实际同臂"）；
- `run_payload` 增加 `arms: [{name, flags, guard_violations, guard_warnings}]`。

### T5.3 误停止率与机制指标

**做什么**

在 `aggregate_metrics` 之外新增一个"编排层指标"聚合（不混进现有六指标）：

```python
def orchestration_metrics(results) -> dict
# {stop_decisions, stop_without_full_evidence, misstop_rate,   # 口径 A
#  gate_hits, gate_blocks, quota_blocks,
#  assessments, overclaimed, assessor_unavailable,
#  gap_reverts, revert_then_resolved, revert_resolved_verified,
#  oscillation_guards, stale_discarded, recall_count}
```

### T5.4 抽查表导出

**做什么**

新增 `--export-review <run_id>`：从 `results[]` 里抽 `case_id / 臂 / raw_output 摘要（截断 500 字）/
ground_truth 要点`，产出 §2.3 的 markdown 表，`判定` 列留空待填。

可选 `--prescreen`：调用 assessor 预筛出"与 ground_truth 直接矛盾"的行，标在备注列（不填判定）。

### T5.5 跑臂（**需分批确认**）

| 批 | 臂 | 次数 | 目的 |
|---|---|---|---|
| 1 | `baseline` | 7 例 × 2 轮 = 14 | 建立参照（阶段 0 的基线可复用，若不改代码则不必重跑） |
| 2 | `arm:state` | 14 | 机制改动最大的一臂，先看它 |
| 3 | `arm:domain` + `arm:budget` | 28 | 域维度两臂 |
| 4 | `arm:inval` | 14 | 失效传播 |

每批跑完先看守卫与抽查表，再决定是否继续。**跑前逐批确认**（外部成本）。

### T5.6 报告

**做什么**

产出 `docs/eval-report-<date>.md`，固定五节：

1. **实验设置**（臂定义、模型、case 集、轮数；明确"样本量 7，不做统计推断"）；
2. **守卫结果**（每臂是否真的施加了 treatment）；
3. **机制指标**（口径 A 的误停止率、门控/配额/核查/回退计数）；
4. **成本**（token in/out、cache 命中、耗时、每例平均委派数）；
5. **结论**——**必须分成两栏**：

| 栏 | 允许写什么 | 例子 |
|---|---|---|
| **机制保证** | 结构上必然成立的性质 | "域闸开启后，被拦派发不再抛异常而是返回结构化结果" |
| **观察到的现象** | 这批样本上看到什么，不给因果 | "7 例中 arm:state 的委派数中位数从 5 降到 4" |
| **不能说** | 任何推断性表述 | ❌ "提升了 20%" / ❌ "显著优于" |

---

## 4. 产出物

| 类型 | 路径 | 说明 |
|---|---|---|
| 代码 | `diagnosis/evaluation/arms.py`（新） | 开关注册表 + 守卫 |
| 代码 | `diagnosis/evaluation/runner.py` | `--arm` / `--export-review` / payload 字段 |
| 代码 | `diagnosis/evaluation/scoring.py` | `orchestration_metrics` |
| 文档 | `docs/eval-report-<date>.md` | 五节报告（含"不能说"栏） |
| 数据 | `eval/runs/<run_id>/` | 逐 case 明细 + 抽查表 |

## 5. 依赖关系

**硬前置**：阶段 0（`decision_counts` / token / cache）、阶段 1–4（开关本身存在）。

**被谁依赖**：无（本阶段是收口）。之后的 E/F 阶段要不要启动，取决于本阶段的结论。

## 6. 决策点（三个）

### 决策点 1：`arm:inval` 不是严格单变量臂，怎么处理

失效传播的有效性依赖"回退后再 resolved 须过核查"，而核查在 `agent_report` 档下不工作。

| 选项 | 臂定义 | 代价 |
|---|---|---|
| **(a) 造一个复合臂（推荐）** | `arm:inval` = `invalidation=on` **+** `strategy=hybrid`，并在报告里**明确标注它含两个变量** | 不能单独归因到"传播"，但能回答"传播+核查这套组合有没有用" |
| (b) 只开传播、核查关 | 严格单变量 | 传播的回退会绕过核查，测的是一个**设计上不完整**的配置，结论没有意义 |
| (c) 不加这臂 | — | 等于放弃验证阶段 4 |

推荐 (a)：诚实标注"复合臂"，比造一个"形式上单变量、实际上残缺"的臂好。

### 决策点 2：抽查由谁判定

| 选项 | 说明 |
|---|---|
| **人工填判定列（推荐）** | LLM 只做预筛（标出可能矛盾的行）；判定必须人填 |
| LLM 全自动判定 | 便宜，但成了"用模型判模型"，与 B2 的初衷冲突 |
| 只抽查有分歧的 case | 省事，但会漏掉"两边都错"的情况 |

### 决策点 3：分批还是一次跑完

| 选项 | 次数 | 说明 |
|---|---|---|
| **分批（推荐）** | 每批 14–28 次 | 每批看完守卫与抽查再继续；某臂明显异常可提前止损 |
| 一次跑完 | ~70 次 | 省人力，但如果某臂配置错，全部作废 |

推荐分批：成本可估、风险可控，且第一批（baseline + state）就能回答最关键的问题。

## 7. 风险与应对

| 风险 | 表现 | 应对 |
|---|---|---|
| **样本量不足却下结论** | 7 例的差异被说成"提升 X%" | 报告固定"不能说"栏；只描述不推断 |
| 臂配置错但看起来有差异 | 守卫没覆盖到某个开关 | 每个开关一条守卫断言；`effective_flags` 写进 payload 可事后核对 |
| 漏触发被误当违规 | 某臂在这批 case 上本来触发不到 | 守卫分"违规 / 未触发"两级，后者只 warn |
| 抽查流于形式 | 只看分数不看结论 | 抽查表留空判定列，**必须有填完的记录**才算本阶段完成 |
| 成本失控 | 70 次单例 × 180 秒 | 分批 + 每批前确认 + 复用阶段 0 的单价估算 |
| 模型随机性掩盖差异 | 同一臂两轮结果差很多 | `--repeat` 已经在阶段 0 修好；报告给每轮原始值（`series`）而非只给中位数 |
| `arm:inval` 被当成纯传播效果 | 结论被高估 | 臂名与报告里都标"复合臂（传播+核查）" |

## 8. 工作量与顺序

| 步 | 规模 | 依赖 live | 备注 |
|---|---|---|---|
| T5.1 开关注册表 + 守卫 | 中 | 否 | 本阶段的地基，守卫写细一点 |
| T5.2 `--arm` | 小 | 否 | 向后兼容 `--variant` |
| T5.3 编排层指标 | 中 | 否 | 误停止率口径要实现成两套 |
| T5.4 抽查表导出 | 小 | 否 | 纯导出 |
| T5.5 跑臂 | — | **是** | 分批，逐批确认 |
| T5.6 报告 | 中 | 否 | 结论分栏是纪律，不是点缀 |

建议顺序：T5.1 → T5.2 → T5.3 → T5.4 →（确认）T5.5 批 1 → 批 2 → …→ T5.6。

## 9. 完成的标准（本阶段出口）

1. **每个臂都能自证**：报告里能看到 `effective_flags`，守卫违规为 0；
2. **误停止率有定义、有数字**（口径 A 为主，口径 B 作参考）；
3. **抽查表填完**：35 行（或实际臂数 × 7）都有判定，`⚠️`/`❌` 的行单独列出来；
4. **结论分栏**：机制保证、观察到的现象、"不能说"三栏都写了，没有一个推断性表述混进第一栏。

至于"这次改造到底值不值"——本阶段只能给**证据**，判断留给读报告的人。
