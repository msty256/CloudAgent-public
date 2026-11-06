# CloudAgent 诊断编排改造记录

> 版本：v1（2026-10-29）
> 仓库：`CloudAgent-public`，起点提交 `0e48a58`
> 本文是**总纲**：记录"为什么改、改什么、改到什么程度算完成、每步怎么做"。
> 过程性材料（源码锚点逐条核对、外部材料阅读笔记）在
> [`diagnosis-orchestration-refactor.md`](./diagnosis-orchestration-refactor.md)，本文引用它而不重复。

---

## 0. 怎么读这份文档

本文的主索引是**改造项的自然语言名字**，括号里的 `A1`、`B2` 这类代号只是历史沿用的简写，
用于在讨论、提交信息、代码注释里指代。**看不懂代号不影响阅读**——每个代号第一次出现时都写了全称，
第 8 节还有统一对照表。

三条阅读路径：

| 你想知道 | 读哪几节 |
|---|---|
| 这东西到底要解决什么问题 | §1（现状与六个问题）→ §3（目标） |
| 每一项改造具体怎么做 | §4（六个改造项） |
| 我该按什么顺序干、怎么验收 | §5（实施顺序）→ §6（度量） |

状态标记只用三种：**已完成**（有代码有测试）、**待做**（设计已定，未动代码）、**暂缓**（明确不做或等结论）。

---

## 1. 起点：CloudAgent 现在的诊断链路

### 1.1 一次诊断是怎么跑起来的

CloudAgent 是一个 Python Agent 运行时（harness）。它在诊断场景下组织了一个**多子代理**结构：

```
用户问题
   │
   ▼
主 Agent（LLM，自己决定下一步派给谁）
   │  调 Agent 工具，subagent_type = "sql-diagnosis" / "log-diagnosis" / "code-diagnosis"
   ▼
_agent_call()  ← Agent 工具的调用实现：主 Agent 派发子代理的唯一入口（cloudagent_ext/tool_system/tools/agent.py:646）
   │  ① 查会话账本：预算够不够、这次该不该停
   │  ② 登记委派（begin_delegation）
   │  ③ 拼提示词：调研协议 + **当前未解决缺口** + 本次目标
   ▼
只读子代理（SQL / 日志 / 代码三个域，各自只能读不能写）
   │  按协议输出结构化结果：证据 / 根因 / 建议 / **缺口**（next_steps + limitations）
   ▼
finish_delegation() → harvest_gaps()  ← 把结果收割成缺口，更新状态机
   │
   └──► 下一轮：主 Agent 看到新的缺口段，决定再派谁
```

**关键设计**：主 Agent 是调度器（它用 LLM 判断），harness 不替它调度。
harness 影响它下一步动作的唯一手段，是**派发点返回的 tool_result**。

### 1.2 缺口机制：这套系统的核心，也是这次改造的靶心

"缺口"（Gap）是一条**待取证命题**：子代理在结果里说明"这件事我该查但没查"（`next_steps`）或
"查了但没查清"（`limitations`）。缺口有四个状态：

| 状态 | 含义 | 谁能进入 |
|---|---|---|
| `open` | 待取证，下一轮会注入给子代理 | 收割时新增 |
| `resolved` | 已被证据覆盖（关键词命中） | 仅从 `open` 进入 |
| `blocked` | 卡住了（缺权限等前提） | 收割时直接置入，或 `open` 被降级 |
| `inconclusive` | 反复复述仍无进展（复述 ≥2 次） | 仅从 `open` 进入 |

运转规则（都在 `cloudagent_ext/diagnosis/runtime_session.py::harvest_gaps`，356 行起）：

- `success`/`partial` 的 `next_steps` → `open`；`failed` 的 `next_steps` → `blocked`；任何状态的 `limitations` → `blocked`；
- 命题必须**含至少一个结构化标识符/数字**才入账（`_actionable`，374-382 行）——纯叙述的"无法判断"不入账；
- 单次收割每类最多 3 条（`_MAX_GAPS_PER_SOURCE`）；
- 某条 `open` 缺口的**全部关键词**都被某条证据的 observation 覆盖 → `resolved`，并把 evidence_id 记进 `evidence_refs`；
- 复述 ≥2 次仍 `open` → `inconclusive`。

这套机制本质上是**诊断域的轻量状态机**：每轮把"当前什么还没查清"注入子代理提示，驱动多轮取证。
用外部方法论的话说，它已经是一个（很粗糙的）CoState——记录"当前什么仍然待办"，而不是回放历史对话。

### 1.3 已确认的六个具体问题

这六条都是读代码核实的，不是推测。每条都标了文件行号，方便日后复核。

**问题 1：停止规则写死在一个函数里，且三套决策词汇互不相通**

`InvestigationSession.decide()` 改造前是五条有序 if-else（`session.py` 原 242-278 行）：
①预算耗尽 → ②最近有 open 缺口 → ③全 blocked/inconclusive → ④已有成功结果 → ⑤继续。
语义规则与预算规则耦合在同一个函数体里，判定顺序写死；加一条规则必须改函数体。

同时仓库里另有两套**互不相通**的决策结构：`query/token_budget.py` 的 `ContinueDecision`/`StopDecision`
（22-23 行为阈值常量）、`services/context_collapse/trigger.py` 的 `CollapseDecision`。
三套词汇无法横向比较，也无法统一统计。

**问题 2：`blocked_only` 在生产路径上不产生任何行为**

`_agent_call` 里派发前只对 `budget_exhausted` 硬停，且仅对诊断域
（`agent.py:720-721`）；`blocked_only` / `success_recorded` 一律只 `logger.debug`
（722-725 行）。注释自认妥协："硬停会打断多域流程（log → sql）"。

也就是说：**缺口状态机算出了"这个域卡住了"，但这个结论被丢掉了**。

**问题 3：缺口没有"来自哪个域"这个字段**

`Gap`（`models.py:601`）字段是 `gap_id / statement / status / restatements / evidence_refs / note`，
**没有 `source_domain`**。而 `gap_summary()`（`runtime_session.py:115-131`）压出来的是**会话级**快照，
没有域维度。→ 任何"按域判断"的想法在当前数据结构上都做不了。

**问题 4：缺口状态"只进不退"**

全仓没有任何一处把 `resolved` 改回 `open`，也没有任何一处解除 `blocked`。
后果：后续证据推翻了早期证据时，**早期结论仍然挂在缺口上**；覆盖性证据到达时，`blocked` 也解不开。
这恰好是 HLD Canvas 帖实证里的核心失败形态——"结论错了，但字段齐全、计算自洽、看起来没问题"。

**问题 5：上下文压缩有盲区，取证结果根本不在压缩范围内**

`context_system/microcompact.py:48-60` 的可压缩工具白名单是从 TypeScript 版移植的**通用编码工具**
（Read/Bash/Shell/Grep/Glob/WebSearch/WebFetch/Edit/Write）。**SQL 取证、日志取证的工具有不在名单里**——
而它们恰恰是产生大结果（行集、日志块）的地方。

同时 `context_collapse/trigger.py` 的三个触发（token 占比、413 报错、以及 `microcompact.py` 里的时间隙）
全是**量驱动/被动反应**，没有内容结构感知。

**问题 6：注入段是"当前未解决缺口"，不是"当前有效状态"**

`_with_open_gaps`（`agent.py:133-180`）把 open 缺口拼成一段纯文本追加到提示词：
最多 5 条、单条 200 字、总长 1000 字，带防注入净化（压平换行、去角色标记）。
但它只告诉子代理"还缺什么"，**不告诉它"已经确认了什么"**。于是每轮都要重新查一遍已知结论，
而且旧结论被推翻时无从察觉。

---

## 2. 外部启示：读到了什么、抄什么、不抄什么

三个来源：一篇论文、一篇社区帖及其两篇衍生方法论、两个参考仓库。
（详细笔记见 `diagnosis-orchestration-refactor.md` §4，这里只留"影响决策"的部分。）

### 2.1 论文：openJiuwen（arXiv:2608.27969v1，2026-08-28）

一个同类 harness 系统的公开设计。两个支柱：

- **Structural Composability**：所有 agent（单 agent / 子代理 / Swarm Flow 里的 agent）复用同一套
  Inner Loop（模型-工具交互）+ Outer Loop（任务级续做）执行引擎，横切能力做成挂在生命周期钩子上的
  **Rail**（有声明优先级，同优先级确定性解决）。加能力只改配置，不改执行循环。
- **Runtime Adaptivity**：在**固定的模型策略**下，让新证据改变上下文构造（κ）、接受与停止判定（Φ）、
  诊断反馈注入（ι）。跨任务的经验沉淀是另一条线（Self-Reflection）。

**对我们直接有用的三点：**

1. **Φ 与资源上限是分开的**（式 10、11）：语义判定 `Φ ∈ {continue, complete, blocked}`，
   资源上限是独立的 `g_cap ∈ {0,1}`，`T = inf{t : Φ_t ≠ continue ∨ g_cap = 1}`。
   → 我们的 `reason` 三值（`gap_open` / `blocked_only` / `success_recorded`）就是 Φ，
   `hard=True`（`budget_exhausted`）就是 g_cap。**A1 的实现与这个式子同构，不要再改**
   （把 action 扩成三值枚举 = 把 g_cap 塞回 action，退回混在一起的老问题）。
2. **结构感知归约是两段式**：先确定性归约（diff / 日志 / 表格），归约不动了再用模型摘要；
   "重复的无效推理或工具调用模式"也在塌缩范围内。→ 上下文改造必须先做纯 Python 的结构化归约。
3. **三种评估策略**：`self`（信自报）/ `independent`（独立核查）/ `hybrid`（混合）。
   → 独立核查不是新组件，是 Φ 的一种策略。

**一条纪律**：论文的 82.6%（SWE-bench Verified）/ 87.19%（Terminal-Bench 2.1）是**编码基准**数字，
分桶分析（按修复时长）作者自己三处声明是 "systems-level interpretation rather than a controlled
causal claim"，且 1–4h 只有 42 例、>4h 只有 3 例。**这些数字不能当本项目的预期效果**，
我们的效果只认自己的对照实验。

### 2.2 HLD Canvas 帖（华为稼先社区，2026-10-16）

面向复杂设计任务的领域 harness 实践。核心实证（同一份信息与约束，60 次运行）：

- 一次性交付 / 集中修改：正确率 **90–100%**；**逐轮修改：20–30%**；
- 错误形态：**字段齐全、计算自洽、结论仍错**；
- 结论：根因不是"交互越多越差"，而是**"当前什么仍然有效"的维护机制缺失**——持续修改是常态，不能靠重来绕过。

三组错位（评价任何 harness 的三问）：执行轨迹 ≠ 业务状态；执行日志 ≠ 业务对象；会话回退 ≠ 状态回退。

CoState 五机制与我们方向的对应：

| 机制 | 含义 | 我们落在哪 |
|---|---|---|
| 单一事实基座 | 专家/Agent/交付件共享同一份可演进状态 | 注入段升级为"当前有效状态"（§4.2 第二小步） |
| 语义化建模 | 类型化节点 + 依赖/冲突/替代边 | 缺口 + `evidence_refs` 解析边（已有，缺域维度） |
| 变更影响传播 | 从变更节点沿依赖边局部遍历 → 受影响集合 → 重算/校验 | 证据失效传播（§4.3） |
| 状态驱动执行 | 每轮状态载体是状态子图而非历史对话 | 已有雏形（decide 读 GapSummary 而非对话） |
| 版本与来源管理 | 变更集 + 来源 + 版本；校验不过不向下游传播 | 缺口 revision（§4.2 第一小步） |

**同样不能用它的 90% / 20-30% 当预期**——那是 HLD 设计域的实证，只作机制依据。

### 2.3 两篇衍生方法论

**《Runtime 优化指南》七条**（逐条标注我们的落点）：

1. 状态载体切换：每轮读"当前状态子图"而非翻历史；旧决策被推翻要显式标记不再注入 → §4.2、§4.3
2. 循环四步化：观察 = **主动检索状态**，不是等工具返回 → 已有（decide 读 GapSummary）
3. 动作分派 + 三重校验：失败返回**结构化错误**（错误码 + 受影响对象 + 建议）而非裸异常 → §4.1 第二小步
4. 影响分析引擎：依赖图 + 变更沿边传播，受影响产物标 stale → §4.3
5. 快慢分层：确定性执行器先跑，未决项才升级 LLM → 贯穿性约束（§6）
6. 失败保护 + 版本化：校验不过**冻结分支不产半成品**；输出"待确认"清单而非硬闯 → §4.2、§4.3
7. 可观测性：导出人类可读**状态视图**（当前有效约束 / 已确认决策 / stale 项 / 待确认项），
   人看的与 Agent 用的是**同一份状态** → `/tasks` 渲染已有，可按此增强

四条落地边界：只对"会发生变更且有下游依赖"的对象建模；保留需求文本与状态的**混合**工作记忆
（纯结构化会丢叙述性上下文）；状态化只对长程、多轮、强关联任务启用；
**状态本身会过期，须定期审计归档**（否则状态层自己退化成历史堆砌）。

**《记忆系统评价指南》五维**（各 0–2 分，<6 分 = 历史堆砌型）：

状态模型（类型化条目 + 有效状态字段 + 关系边，权重最高）／写入（更新式 + supersede 仲裁，
**禁止默默并存**）／检索（按需取，禁全量注入 + 质量反馈回路）／生命周期（归档、降级、低质量召回复核）／
可观测（可读**可改** + 审计统计）。

成熟度阶梯：L0 无记忆 → L1 追加式摘要 → **L2 结构化状态（加 valid/supersedes/checkedAt，
成本最低杠杆最大）** → L3 关系边 + 级联失效 → L4 反馈闭环（misleadingCount ≥2 自动降级复核）。

五误区：记忆越多越好 ≠｜上下文够长 ≠ 会被正确应用｜记录轨迹 = 掌握状态 ≠｜
回退会话 = 回退状态 ≠｜召回统计 = 反馈回路 ≠（必须记"用了**且用对了**"）。

### 2.4 参考仓库：可抄的十五件事

内核 `agent-core`（pinned `0ab5913`）+ 产品层 `jiuwenswarm`（`master` 分支）。

| # | 位置 | 机制 | 抄到哪 |
|---|---|---|---|
| 1 | `harness/rails/task_completion_rail.py:190-216` | `build_evaluators()`：MaxRounds / Timeout / CompletionPromise 组成**有序链**，语义停止与硬限制都是可插拔评估器，没有 if-else 分派 | §4.1（已落地） |
| 2 | `harness/goal/schema.py:167-182` | `GoalRecord` 有 `revision` / `attempt_count` / `last_assessment` / `last_stop_reason` | §4.2 第一小步 |
| 3 | `harness/goal/schema.py` | `GoalStatus`（active/paused/completed/blocked）与 `GoalAssessmentStatus`（continue/complete/blocked）**两套分开** | §4.2 第二小步 |
| 4 | `harness/goal/schema.py` | `GoalStopStrategy = agent_report \| transcript \| hybrid` | §4.2 第三小步的三种策略原型 |
| 5 | `harness/goal/evaluation.py:155-210` | **HYBRID 八条规则**：信任 CONTINUE；只核查 COMPLETE/BLOCKED；`verification_interval` 到了抽查一次 CONTINUE；冲突以 transcript 为准；核查不可用则保守回落 continue | §4.2 第三小步（**关键：抄调度，不是抄形态**） |
| 6 | `harness/goal/evaluation.py:264-270` | `should_spot_check`：`attempt_count > 0 and attempt_count % interval == 0` | 同上 |
| 7 | `harness/goal/evaluation.py:289-336` | `_apply_hard_limits`：**只有 CONTINUE 能被硬限制推翻**，命中后产 `BLOCKED + evidence="max_attempts_exhausted: n/m"` | §4.1 第三小步（配额耗尽要给可读证据串，不只给枚举） |
| 8 | `harness/rails/task_completion_rail.py:746-766` | 轮次前后三条件校验：`status ∈ allowed` ∧ `goal_id` 相等 ∧ `revision` 相等，任一不符**丢弃本轮结果** | §4.2 第一小步 |
| 9 | `harness/goal/manager.py:179,196,217-221` | **in-flight 期间不递增 revision**；idle/BLOCKED 恢复时才递增；resume 时若正在跑则保留 | §4.2 第一小步的关键细节（写错会作废正在飞的结果） |
| 10 | `harness/rails/AGENTS.md` | priority 梯队 100→70；"**同一个数字排两件事：init 顺序与回调链顺序**"；同 priority 靠稳定排序保注册序 | 远期（hooks 补 priority） |
| 11 | `core/context_engine/schema/config.py:11-22` | `CompressionRecallConfig{enabled, chunk_size_tokens=3000, chunk_overlap_tokens=300}` | §4.4 句柄存储参数起点 |
| 12 | `.../forked/compressor/base.py:717-745` | 归档失败 → **不留召回标记**，继续无召回（"校验不过不向下游传播"）；摘要带 `[[COMPRESSION_RECALL: id=…]]`；`enable_reload` 监听模型输出里的 `[[HANDLE:xxx]]` 自动回灌 | §4.4（句柄先落库成功，才允许替换原文） |
| 13 | `rails/context_engineer/context_processor_rail.py:52-131` | 处理器按 `(processor_key, config)` 成对注册，`priority=85`，按键 add-or-replace | §4.4（插拔，不是加 if） |
| 14 | `symphony/flow/engine.py` | ingest → distill（`min_successes`、`min_pack_success_rate=0.8`）→ 脱敏 → `PackageReviewGate.review` → **versioned recipe** → install | §4.5（入库卫生条件的现成参照） |
| 15 | `jiuwenswarm/agents/swarm/DESIGN.md`（master） | 三问判定（属性→params / 环境→context / 句柄→工厂直读）；"`ctx.config` 是伪装成环境的属性源"；声明文档**单一写者** | §4.2（净化参数是属性）+ §4.3（单写者） |

### 2.5 明确不抄

1. **不整体移植 Rail 体系**：我们的 hooks 已覆盖同类职能，只差 priority 元数据（`hooks/registry.py:27`
   的 `RegisteredHook` 只有 `registration_order`）。补字段是几行代码的纪律项，不是架构项。
2. **不建独立调度器 / 仲裁器**：`agent_teams/workflow/engine/primitives.py` 2173 行只是普通 async
   函数库（`budget/parallel/pipeline/agent/human`），jiuwen 自己也没造调度器。我们的主 Agent 就是调度器。
3. **不建独立 goal_manager 状态存储**：GoalRecord 的职责并进 `InvestigationSession`。
4. **不建全量依赖图**：HLD 帖评论区自认建模成本重；影响传播限定在"证据 → 缺口"解析边内，
   而这条边**已经存在**（`Gap.evidence_refs`）。
5. **不动"缺口段在 objective 之前"的位置**：这是实测过的注意力排序。
6. **不改 `action` 语义**（见 §2.1 第 1 点）。

---

## 3. 改造总目标

### 3.1 三层目标

**第一层 · 可归因**（"这次为什么停"能回答）
停止判定从写死的顺序变成可插拔评估器链，每次停能说出**是谁判的、判的哪一级、判的哪个域**。
交付后可以宣称：`blocked_only` 从死路径变成真实行为；停止原因可统计。

**第二层 · 状态可信**（"这个结论现在还成立吗"能回答）
缺口状态引入版本与来源，注入段从"还缺什么"升级为"当前什么有效"；新增独立核查，
对子代理**自报**的完成结论做抽查，并把"关键词判定 vs 独立判定"的分歧率量化。
交付后可以宣称：陈旧写入归零（结构保证）；分歧率有数。

**第三层 · 可度量**（"改得对不对"能用数据说）
先造尺子（基线落盘），再做单变量对照（每臂只动一个变量 + 开关泄漏守卫），
并强制做**结论级正确性抽查**——因为评分器打的是结构化字段分，字段齐全、结论仍错是这类系统的典型假阳性。
交付后可以宣称：机制效果（结构保证的那部分）与统计效果（需要样本量支撑的那部分）分开陈述。

### 3.2 能宣称什么、不能宣称什么

| 类别 | 例子 | 什么时候能说 |
|---|---|---|
| **机制保证** | `blocked_only` 生效、陈旧写入归零、多域不误伤、回退可追踪 | 改完 + 对应测试全绿即可说 |
| **统计效果** | 诊断成功率提升 X%、平均委派数下降 Y% | **必须等对照数据**；样本 <30 时只能描述不能推断 |
| **论文/帖子数字** | 82.6% / 87.19% / 90%→20-30% | **永远不说成本项目预期**，只在解释机制时引用并注明出处与"非因果"声明 |

---

## 4. 六个改造项

每一项都按同一模板写：**问题 → 为什么这样改 → 具体做什么 → 成果与验收 → 状态**。
代号（如 `A1`）只在标题后作标签。

---

### 4.1 停止决策：从写死的判定顺序，改成可插拔的评估器链

**标签** A（含三小步 A1 / A2 / A3）

#### 问题

见 §1.3 问题 1、问题 2、问题 3。三套决策词汇互不相通；五条规则写死在一个函数；`blocked_only` 被丢弃；
缺口没有域维度，所以连"按域停"的数据前提都没有。

#### 为什么这样改

- 参照论文式(10)(11)：**语义判定（Φ）与资源上限（g_cap）必须分开**。
  它们混在一起时，"资源耗尽"和"证据不足"在统计上无法区分——误停止率这个指标就永远算不出来。
- 参照 `build_evaluators()`：有序链 + 显式优先级，而不是在一个函数里 if-else。
  但**不建独立仲裁器**——jiuwen 自己也是链 + priority（§2.5 第 2 条）。
- 域级停止的正确落点不是新组件，而是**派发点的域闸 + 结构化 tool_result**：
  主 Agent 是调度器，harness 只能通过 tool_result 塑形它下一步选择。

#### 第一小步：统一的决策协议 + 评估器链　`A1`　**已完成**

做了什么：

| 文件 | 内容 |
|---|---|
| `cloudagent_ext/query/stop_decision.py`（新增 191 行） | 协议 `StopDecision{action, scope, hard, domain, reason, evaluator}`；`decision_tier()`；纯函数 `fold_decisions()`；`StopEvaluator` Protocol；`EvaluatorChain` |
| `cloudagent_ext/diagnosis/evaluators.py`（新增 160 行） | `DiagnosisStopContext`（一次判定所需的全部输入，只读快照）+ 五个评估器 + `build_default_chain()` |
| `cloudagent_ext/diagnosis/session.py` | `decide()` 的五条 if-else → 链上全量评估 + 折叠；`SessionDecision` 增加 `evaluator` 归因字段（默认空，向后兼容） |
| `tests/diagnosis/test_stop_decision.py`（新增 292 行） | 折叠优先级、归因、单评估器、**与旧实现逐条等价的 36 组表驱动用例**、通用层纯净性检查 |

折叠规则：`hard`（g_cap，如预算）> 域级 > 会话级；同层用**稳定排序**保注册序，
所以"注册序即优先级"这件事写在链的构造处，不散落在 if-else 里。

五个评估器与原五条规则一一对应，**注册序 = 原判定顺序**：

```
budget_exhausted(hard) → gap_open → blocked_only → success_recorded → budget_available(兜底，永不弃权)
```

成果：

- `reason` 字符串逐字未变（对外契约不变），但多了 `evaluator`——**谁判的**现在可归因；
- 语义等价是**可证明的**：把旧 if-else 逐字复刻成 `_legacy_decide()`，对
  「缺口形态(6) × 预算(0/14/15) × 是否有成功结果(2) = 36 组状态」逐一比对 `(should_continue, reason)`；
- 验收结果：`test_gap_orchestration.py` + `test_session.py` 的 decide 用例**一行未改全绿**（54 passed），
  新增测试 59 passed，诊断域全量 **597 passed / 25 skipped**（改造前基线 538 passed / 25 skipped）。

**范围收窄说明**：原计划说"三套决策词汇收敛成一套"，实际只收敛了诊断域这一侧。
`token_budget.py` 与 `context_collapse` 的决策类**没动**——并进去要改它们的公开契约与既有测试，
属于独立一步，排在 §5 的可选阶段。协议本身已能容纳它们（`scope=delegation` + `reason` 就够）。

#### 第二小步：给缺口加域维度，派发前做域级拦停　`A2`　**待做（阻塞在规则决策）**

做什么：

1. `Gap` 加 `source_domain` 字段（默认空），`harvest_gaps()` 收割时传入委派类型
   （`finish_delegation` 手上就有 `task.agent_type`，原料齐）；
2. `gap_summary()` 增加按域切分的能力；
3. `runtime.domain_gate(domain)` 返回该域的判定；`_agent_call` 派发前调用，
   被拦时返回**结构化 tool_result**（复用现有 `_diagnosis_stopped_result` 的模式：
   含该域缺口清单、状态、原因；必须带 `status`/`error` 两个键，否则模型侧收到空结果——
   这是历史上已经踩过的坑，见 `agent.py:183-195` 的注释）；
4. 用 A1 的协议承载：域级判定 = `StopDecision(scope=domain, domain=..., reason=...)`。

**待定的设计决策（必须定下来才能动手）**：

现有测试 `test_blocked_only_is_advisory`（`test_gap_orchestration.py:427-440`）把"同域、有 blocked 缺口、
换个目标再派**必须放行**"写成了契约。而"域级拦停"天然会拦掉它。三个选项：

| 选项 | 规则 | 代价 |
|---|---|---|
| 严格 | 该域出现 blocked-only 就拦该域**一切**派发 | 必须改那条测试；"同域换问题继续查"被误伤 |
| **同目标（推荐）** | 只在"本次 objective 覆盖该域某条 blocked 缺口的关键词"时拦——拦的是**用同一问法死磕已知取不到的证** | 测试零改动；语义更贴目标；多一次确定性关键词判定 |
| 缩到配额 | 只做域配额（第三小步），blocked 不拦 | 最小改动，但 `blocked_only` 仍是死路径（等于没解决） |

推荐"同目标"的依据：论文的 `Φ=blocked` 是**任务级**判定，我们是**域级**（粒度更细）；
"blocked"意味着"这个问法推进不了"，不是"这个域死了"。

验收标准：新增多域用例——单域 blocked 时该域派发被拦、其他域照常。

#### 第三小步：按域配额　`A3`　**待做**

做什么：`BudgetView(domain)`（域配额 + 共享余量），挂 runtime；作为一个具体评估器进链
（`scope=domain`）。配额耗尽时产出**可读证据串**（照 `_apply_hard_limits` 的
`max_attempts_exhausted: n/m` 格式），而不是只给一个枚举值。

为什么需要：它精确解决"`blocked_only` 不能硬停"的两难——单域死磕被配额掐死，多域流程被保护。
总预算（含非诊断委派，防绕过的设计）必须保留，且仍是会话级硬停。

验收标准：单域耗尽不误停其他域；总预算用尽仍会话级硬停；非诊断委派计入总预算。

---

### 4.2 缺口状态的可信度：从"只进不退"，改成有新旧概念

**标签** B（含三小步 B1a / B1b / B2）

#### 问题

见 §1.3 问题 4、问题 6。状态没有版本，注入段只有"还缺什么"，"成功"靠子代理自报，
判定靠 `TERM_EQUIVALENTS` 词表（这张词表同时影响评分口径与生产判定，改动等于改生产行为）。

#### 为什么这样改

- 版本与来源是 CoState 第五机制，也是记忆评价指南的 L2 核心跃迁（加 `validity` / `supersedes` /
  `checkedAt`，"成本最低杠杆最大"）；
- 独立核查对应论文的 `independent assessment` 策略——**它不是新组件，是 Φ 的一种策略**；
- 注入段升级对应"单一事实基座"：让主 Agent 每轮看到"当前什么仍然有效"，而不只是"还缺什么"。

#### 第一小步：缺口带版本号，陈旧写入作废　`B1a`　**待做**

做什么：

1. 会话层加 `revision`（目标变更 / 缺口状态大批量变更时递增）；
2. 注入段携带当前 `revision`，收割时校验；不符则**丢弃该次写入**（照 `_validate_goal_state`
   的三条件：status 合法 ∧ 目标一致 ∧ revision 一致）；
3. **in-flight 期间不递增 revision**（照 `manager.py:179/217-221`）——
   否则改目标时会把正在执行的委派结果全部判成陈旧，症状是"改目标后证据全丢，而日志一切正常"；
4. 净化参数（条数上限 / 单条字长 / 白名单）从写死改为配置，且**在装配期烘焙成值**，
   不在每次调用时读环境变量（依据三问判定：这类值是"属性"不是"环境"）。

验收标准：新增可观测计数器（陈旧写入次数，预期恒 0）；状态段长度有上限；注入开/关行为正确。

#### 第二小步：注入段升级为"当前有效状态"　`B1b`　**待做**

做什么：把那一段从"## 当前未解决缺口"改成三块——
**open 缺口**（还缺什么）+ **已确认的关键结论**（resolved 且抽查通过）+ **各域预算余量**。

硬约束：段落仍压在 objective 之前（不动实测过的注意力排序）；长度预算严格受限；
净化规则不变（单条 200 字、禁换行、防角色标记注入）。

注意：能进"已确认结论"的条件是 resolved **且**过了独立核查——所以 B1b 的完整效果依赖 B2。

验收标准：改目标后旧轮快照不写入；状态段长度上限生效。

#### 第三小步：独立完成核查　`B2`　**待做**

做什么：按论文的三种策略实现，**默认 HYBRID**（照 `evaluation.py:155-210` 的八条规则）：

- 子代理报 `continue`（= 还有缺口）→ **直接信**，不核查（省成本）；
- 子代理报终态（= resolved / 完成）→ **必须核查**；
- 每 `verification_interval` 次，即使报 continue 也抽查一次；
- 核查器与子代理结论冲突 → **以核查器为准**；
- 核查器不可用 → 保守回落 continue（不轻信）。

核查器的执行形态照抄四个约束：无工具、`temperature=0`、输入为捕获的真实消息、
**64k 字符尾部截断**、`interrupt` 轮跳过评估（不烧 LLM 调用）。

**注意**：这四个约束只是形态；真正的成本控制在**调度**（上面五条）。只抄形态会变成每轮多花一次 LLM 调用。

验收标准：产出"独立核查 vs 关键词判定"的分歧率报告；`agent_report` / `transcript` / `hybrid`
三种策略都可通过配置切换（这样"核查策略"本身才能作为实验变量）。

---

### 4.3 证据失效传播：被推翻的结论要能回退

**标签** C2

#### 问题

见 §1.3 问题 4。`resolved` 不可回退、`blocked` 不可解除，两个"错误终态"。

#### 为什么这样改

HLD 帖的核心实证就是"旧结论残留在交付件里"。它给的解法是"变更影响传播"——
但**不建全量依赖图**（建模成本重，帖评论自己承认）。我们的数据基础已经现成：
`Gap.evidence_refs` 就是"证据 → 缺口"的解析边。

#### 做什么

1. 证据被后续证据**推翻/修正**时，由它解析的缺口从 `resolved` 回退为 `open（待复核）`，
   并沿 `evidence_refs` 记录回退原因（来源 + 版本）；
2. 覆盖性证据到达时，`blocked` 缺口解除回 `open`；
3. 回退的缺口重新进入派发循环；**再次 resolved 必须经 B2 独立核查确认**
   （快慢配对：确定性传播走关键词/结构匹配快路径，可疑回退才走 LLM 慢路径）；
4. **缺口状态改由单一写者独占**（`GapStore`）：收割与回退两个调用方都只提交变更请求，
   不直接改 `gap.status`。依据 `swarm/DESIGN.md` §11 的教训——两个写者时"胜负由调用顺序决定"。

#### 成果与验收

- 新增用例："证据推翻 → 缺口回退"、"覆盖证据 → blocked 解除"，风格照 `test_gap_orchestration.py`；
- 专有指标：缺口回退次数、回退后再次 resolved 的一致率；
- 作为对照实验的独立一臂。

**依赖**：B2（"回退后再 resolved 须经独立核查"没有 B2 就是空话）。

---

### 4.4 上下文：补上取证工具的压缩盲区，加证据句柄

**标签** C1

#### 问题

见 §1.3 问题 5。压缩白名单不含取证工具；触发全是量驱动，没有结构感知。

#### 为什么这样改

论文 §2.2 的三段式：渐进压缩 → **结构感知归约（确定性优先、模型兜底）** → 卸载与检索
（完整内容 → 摘要 → 紧凑句柄 → 按需检索）。
参考实现的成对设计（`CompressionRecallConfig` + `archive` 机制）：**卸载必有召回**，
且归档失败就不留召回标记（不向下游传播半成品）。

#### 做什么

1. 触发链加**结构处理器**（不是替换触发，是加一类）：SQL 行集按列聚合、日志按错误指纹聚类；
   锚点可复用 `text_match.py` 的关键词逻辑。**先纯 Python 归约，归约不动才考虑模型摘要**；
2. 证据原文 offload 到 `ev:` 句柄存储（参数起点：chunk 3000 tokens / overlap 300）；
3. 活跃上下文里留句柄 + 摘要 + 召回标记；模型显式请求时按需取回（由粗到细：
   先定位轮次，再恢复原文）；
4. 处理器按 `(key, config)` 成对注册、add-or-replace，**不要加 if 分支**。

#### 硬约束与验收

- **不得破坏 prompt cache 前缀稳定性**：`prompt_assembly.py` 已按
  GLOBAL / SESSION / REQUEST 分组打 `cache_control` 标记（612-625 行注释），任何压缩改造不能改前缀结构；
- 验收：cache 命中率不回退 + 长案例子集对照；
- **必须先有 token 度量**（§5 第一阶段），否则改完无法判断是不是把尺子改了。

---

### 4.5 经验沉淀：从成功轨迹到可复用能力包

**标签** E　**暂缓**

#### 现状

零件已有（`rules_learner.py` / `sop_converter`），但对照实验结论未验证——在没有证据的情况下
把轨迹沉淀成规则，风险是把噪声固化成规则。

#### 已定的规格（开工时直接照此实现）

```yaml
type: rule|fact|experience            # 类型化（记忆评价指南的五维第 1 维）
validity: active|superseded|archived  # 当前是否有效
supersedes / supersededBy: ...        # 冲突必须显式推翻，禁止默默并存
checkedAt: 2026-10-29                 # 超期未确认自动降级 archived
misleadingCount: 0                    # 达阈值（≥2）自动降级待复核
appliesTo: [domain-tags]              # 按域标签局部拉取，禁止全量注入
```

入库卫生条件（照 `symphony/flow` 的流水线）：**success-only** → 结构分组蒸馏
（`min_successes`、`min_pack_success_rate=0.8`）→ **评审门** → 脱敏 → **版本化** → 安装。

#### 时机

等对照实验（§6）的结论出来再启动。理由：现在还不知道"多轮取证"到底有没有收益，
先沉淀可能把错误做法固化。

---

### 4.6 记忆系统自评：给本仓的记忆机制打分

**标签** F　**暂缓（可选，小）**

#### 做什么

用记忆评价指南的五维（状态模型 / 写入 / 检索 / 生命周期 / 可观测，各 0–2 分）
对 CloudAgent 自身的 memdir / remember 机制打分，产出"当前处于 L 几 + 从 L1 升到 L2 的清单"。

#### 为什么值得做

它和 §4.5 同源方法论；半天工作量，能给后续的经验沉淀提供同一把尺子。
但优先级低——不挤占前四项。

---

## 5. 实施顺序

排序原则：**先能度量 → 再把"停得对不对"做实 → 再让状态可信 → 再动上下文 → 最后做会改变结论的传播 → 才谈统计结论**。

| 阶段 | 目的 | 主要工作 | 出口标准（此时可以宣称什么） | 规模 | 依赖 |
|---|---|---|---|---|---|
| **0 度量地基** | 让"效果"第一次可被测量 | 固定依赖清单；跑 live 基线并把指标落盘（委派数 / 终止原因分布 / 缺口流转 / token / cache 命中）；确认评测走的是**主 Agent 派发路径**而非直驱子代理 | 同一 commit 连跑两次结果一致；基线 JSON 入库 | 小 | — |
| **1 停止判定 + 域维度** | 停得对、可归因、按域生效 | §4.1 的三小步（第一小步已完成） | 能回答"为什么停、停在哪个域"；单域停不误伤其他域 | 中 | 阶段 0 |
| **2 状态可信** | 每轮看到的是当前有效状态 | §4.2 的三小步 | 陈旧写入计数 = 0（结构保证）；分歧率报告 | 中 | 阶段 1 |
| **3 上下文** | 长案例不因取证结果爆上下文 | §4.4 | cache 命中率不回退；长案例子集对照 | 大 | 阶段 0（token 度量必须先有） |
| **4 证据失效传播** | 被推翻的结论不再残留 | §4.3 | 两个新用例全绿；回退次数与一致率可统计 | 中 | 阶段 2、3 |
| **5 对照实验** | 机制效果与统计效果分开说 | 分臂跑 + 结论级抽查（§6） | 一份"哪些是机制保证、哪些有统计支持"的报告 | 中 | 阶段 1–4 |
| **6 可选/延后** | 不影响主线 | §4.5 经验沉淀、§4.6 记忆自评、hooks 补 priority、三套决策词汇收敛 | 各自独立小交付 | 小 | 阶段 5 结论 |

### 5.1 四条不能破的顺序约束

1. **阶段 1 之前不碰上下文（§4.4）**：压缩会改变 token 与上下文长度，度量没建立之前动它，等于先把尺子改了。
2. **§4.1 第二小步（域归因）必须先于 §4.2 第二小步（状态段）**：两者共用 `source_domain`，否则返工。
3. **§4.3 依赖 §4.2 第三小步**："回退后再 resolved 须经独立核查"没有核查器就是空话。
4. **阶段 0 必须确认评测口径**：评测执行器有两种派发模式，只有一种会经过缺口编排（见 §6.1）。

### 5.2 阶段提案索引

每个阶段有独立的详细提案（目标 / 任务步骤 / 产出物 / 依赖 / 风险 / 决策点）。
**本表是入口，提案是执行时看的那份。**

| 阶段 | 提案文件 | 决策状态 | 是否需 live | 规模 |
|---|---|---|---|---|
| 0 度量地基 | [`proposals/phase-0-measurement.md`](./proposals/phase-0-measurement.md) | 三点已定；**T0.1–T0.6 已实现**（基线未跑） | 是（L3 基线，待确认后跑） | 小 |
| 1 停止判定 + 域维度 | [`proposals/phase-1-stop-decision-domain.md`](./proposals/phase-1-stop-decision-domain.md) | 三点已定；**T1.1–T1.6 已实现** | 否 | 中 |
| 2 状态可信 | [`proposals/phase-2-state-trust.md`](./proposals/phase-2-state-trust.md) | 三点已定；**T2.1–T2.5 已实现**（live 验证待确认） | 是（T2.3 单例验证） | 中 |
| 3 上下文 + 句柄 | [`proposals/phase-3-context-compaction.md`](./proposals/phase-3-context-compaction.md) | **T3.0–T3.5 已实现**（召回 = 工具式）；live 对照待额度 | 是（压缩开/关对照） | 大 |
| 4 证据失效传播 | [`proposals/phase-4-invalidation.md`](./proposals/phase-4-invalidation.md) | **T4.1–T4.4 全部实现**；修正了 `conflict` 跨轮引用被丢弃的阻塞 | 否 | 中 |
| 5 对照实验 | [`proposals/phase-5-experiments.md`](./proposals/phase-5-experiments.md) | **前置已就绪**（阶段 3/4 开关 + 守卫用例）；多臂预设与跑批待做 | 是（分四批） | 中 |
| 6 可选/延后 | 未写提案（E 经验沉淀 / F 记忆自评） | — | — | 小 |

**已定的决策都写在每份提案末尾的「决策记录」小节里**（带日期与影响），
不必回翻对话。阶段 5 的三个决策点（`arm:inval` 形态 / 抽查判定方式 / 分批策略）**尚未定**，
等要跑实验时再定。


---

## 6. 度量与实验设计

> **基线状态：尚未采集。** 采集代码（`decision_counts` / `gap_events` / `usage` / `repeat` 聚合 /
> 派发模式自证）已落地并有 44 个用例守住，但**真实模型的基线数字还没有**——
> 阶段 0 的 T0.7 需要先测机时单价再决定规模，见提案 §10.5。
>
> **首次 live 实测（2026-11-01，`code-001`、main 派发）发现一个必须先解决的问题**：
> 1 例耗时 123.6 s、`model_calls` 打满 30 轮、`delegations` 仅 1 次、输入 **143 万 token**，
> 且 `counts["invalid_output"] = 1`。
>
> 根因：`main` 模式下 `LiveExecutor.raw_output` 取的是**主 Agent 的散文**，
> 而评分器要求诊断协议 JSON。所以 **main 模式下正确率恒为 0%**——不是诊断失败，是量错了对象。
>
> **更前置的一个（已修）**：那次运行的 `model_calls` 打满 30 轮、`tool_calls` 40 次是主 Agent
> **自己查**、只派 1 次子代理——`main` 模式的系统提示是通用那套，从没要求过委派。
> 已追加 `_MAIN_DISPATCH_CONSTRAINT`（取证必须委派 / Read·Grep 只用于理解任务 /
> 不用阅读印象代替取证 / 作答要指出依据）。
>
> **加约束后复跑（同日）**：主 Agent 自查 40 → **7** 次、委派 1 → **3** 次，约束生效。
> 但这一跑仍不能验证缺口机制：① 需要 266 s 而超时设 180 s，被腰斩；
> ② `code-001` 的子代理答得完整，`gaps_total = 0` → 没有缺口，注入必然为 0（这是正确行为）；
> ③ 3 次委派里有 1 次是 `test-runner`（非诊断域，不进缺口账本）。
> → **验证缺口机制要换一道会产生缺口的题**（`code-007` 两条 required_evidence 或 `cross` 域），
> 并把 `--timeout-per-case` 提到 300–360 s。
>
> 阶段 5 开工前还必须定"评谁的结果"（见阶段 5 提案 §1 的阻塞项）。
> **已修（2026-11-01）**：`--grade-source {auto,main,subagent}`（默认 `auto`）。
> `auto` 在 `main` 派发下评**子代理的协议结果**（`entry.result`），主 Agent 的回答留在
> `case.main_answer`。注意口径：它衡量的是"子代理结论对不对"，不是"主 Agent 转述得准不准"。
>
> **修完立刻暴露出一个更根本的问题（2026-11-01，`code-007` 重跑）**：
> 评分终于能跑了（`category=parsed`、证据充分率 100%、建议可接受 100%），
> 但 **Top-1 根因命中率 0%**。逐条核对后发现：**是 ground_truth 过期，不是诊断错了**。
>
> - `code-007` 的 gt 写的是"协议校验后处理只挂在同步分支：`is_async` 为真时提前 return"；
> - 但 `agent.py:1877-1879` 的注释明确写着这次已被修掉：
>   "wire-investigation-session：异步结果也走同一套入账 + 协议后处理（**旧实现里 if is_async
>   提前返回**，`_AUGMENTERS` 只存在于同步分支，异步拿不到校验块）"；
> - 子代理给出的两条候选与此一致（它判断"观测来自历史版本，与当前源码不符"），
>   并且指出了**当前真实存在的不对称**：异步路径确实**不执行 `_run_assessor`**
>   （`agent.py` 里 `_run_assessor` 只在同步分支 1388 行被调用，异步分支 0 处）。
>
> 含义：**这套 case 集里可能还有其他"标准答案已随代码演进失效"的题**。
> 在阶段 5 做任何对照之前，必须先给 case 集做一次体检（逐题确认 gt 所述行为是否仍成立），
> 否则正确率指标量的是"背旧答案的能力"。已列为阶段 5 的前置任务。
>
> **体检已完成（2026-11-01）**：38 题全核，**17 题可静态复核、15 题需运行期环境、6 题依赖仓外项目**；
> 3 道过期题已按代码证据修正（含 `forbidden_findings` / `observation_terms` 的配套反转）。
> 每题现在带 `ground_truth.verification ∈ {static,runtime,external}` 与 `verified_against`，
> `python -m cloudagent_ext.diagnosis.case_audit` 可随时打出分布。
> 详见 [`case-audit-2026-11-01.md`](./case-audit-2026-11-01.md)。
> **算正确率只能用那 17 题**——把 runtime/external 混进分母会得到"看起来能跑"的数字。


### 6.1 先说一个容易踩的坑：评测走哪条路

评测执行器 `LiveExecutor` 有两种装配（`evaluation/executors.py:277-330`）：

| 模式 | 加载 Agent 工具 | registry 内容 | 是否经过 `_agent_call`（缺口注入 / decide / 域闸都在这里） |
|---|---|---|---|
| `direct`（默认） | 否 | 只有子代理自己的工具 | **否** |
| `main` | 是 | `{Agent, Read, Grep, Glob, Skill, TodoWrite}` + 全量主 Agent 提示 | **是** |

**基线必须用 `main` 模式**，否则测的是"子代理单独干活"的能力，与本次改造无关。
自检手段：`direct` 模式下 `injected_dispatches` 恒为 0，对比报告会打"treatment 未施加"。

### 6.2 指标

| 类别 | 指标 |
|---|---|
| 效果 | 诊断成功率、每结论平均委派数、**误停止率** |
| 成本 | token（input / output 分开）、cache 命中率、注入段长度分布 |
| 编排 | 各域被正确停止 / 恢复的比例、缺口回退次数、回退后再次 resolved 的一致率 |
| 一致性 | 独立核查 vs 关键词判定的分歧率 |

### 6.3 分臂（每臂只动一个变量）

`Baseline`（现五规则）/ `停止判定评估器链` / `+域配额` / `+状态可信` / `+证据失效传播`。
每臂沿用现有的"开关泄漏"守卫思路（`gaps-off` 臂若出现 `injected_dispatches > 0` 即 fail，
见 `evaluation/runner.py:350-352`），每个新变量都要有自己的守卫。

### 6.4 结论级正确性抽查（必做）

HLD 帖最大的教训是"字段齐全、计算自洽、结论仍错"。评分器打的是结构化字段分，
所以每臂必须另抽小规模样本（如 10 例），核对**业务结论本身**的正确性（人工或 LLM 辅助）。
**不做这一步，指标好看也没有意义。**

### 6.5 不做的事

- **不做分桶统计**：case 集总共 38 例（sql 14 / code 7 / log 6 / cross 6 / sync 5），
  分桶后每桶个位数，任何比例都不可信。论文自己的 1–4h 桶只有 42 例、>4h 只有 3 例，作者都不下强结论。
- **不做显著性检验**：样本量不支撑。

---

## 7. 风险与边界

| 风险 | 表现 | 处置 |
|---|---|---|
| 评测跑错派发模式 | 测到的不是缺口编排 | 基线一律 `main`；用 `injected_dispatches > 0` 自检 |
| case 集太小（38 例，单域最少 5 例） | 比例型指标不可信 | 只做结论级抽查，按域分层报告 |
| `sql` / `sync` 域依赖外部 Postgres（`cloudagent_sim` 上/下游） | 该两域 live 可能大量崩溃，看起来像缺陷 | 先用 `code` 域（诊断本仓代码，无外部依赖） |
| 单例 live 可达 180 秒且烧 token | 全量成本不可控 | 先跑 1 例 → 3 例估单价 → 再决定全量规模 |
| 域级停止是论文里没有的场景 | 没有现成参照，只能自证 | 唯一闸门：单域停不误伤其他域（多域用例） |
| 版本号与并发委派 | 实现写错时症状隐蔽（"改目标后证据全丢"而日志正常） | 照 in-flight 不递增的三态实现，并补并发用例 |
| 环境两套依赖 | 单测能过但 live 跑不起来（缺 httpx / openai 等） | 单测依赖与 live 依赖分开验；live 前先确认 provider 能构造 |
| 状态层自身膨胀 | 缺口/经验条目越积越多，退化成历史堆砌 | 超期未确认自动降级归档（`checkedAt` 机制） |

---

## 8. 术语与代号对照

**代号**（历史沿用，出现在代码注释与提交信息里）：

| 代号 | 全称 | 本文位置 | 状态 |
|---|---|---|---|
| A / A1 | 停止决策统一 · 协议 + 评估器链 | §4.1 第一小步 | **已完成** |
| A2 | 停止决策统一 · 域归因与域级拦停 | §4.1 第二小步 | 待做（阻塞在规则决策） |
| A3 | 停止决策统一 · 按域配额 | §4.1 第三小步 | 待做 |
| A4 | 三套决策词汇收敛（原 A 的延伸） | §4.1 范围收窄说明 | 暂缓（可选） |
| B1a | 状态可信 · 版本号与陈旧写入作废 | §4.2 第一小步 | 待做 |
| B1b | 状态可信 · 注入段升级为当前有效状态 | §4.2 第二小步 | 待做 |
| B2 | 状态可信 · 独立完成核查 | §4.2 第三小步 | 待做 |
| C1 | 上下文 · 结构感知压缩 + 证据句柄 | §4.4 | 待做 |
| C2 | 证据失效传播 | §4.3 | 待做 |
| D | 按域预算视图 | 并入 §4.1 第三小步（A3） | 待做 |
| E | 经验沉淀 | §4.5 | 暂缓 |
| F | 记忆系统自评 | §4.6 | 暂缓（可选） |
| P0 / P5 | 阶段 0 度量地基 / 阶段 5 对照实验 | §5、§6 | P0 采集层已完成（基线未跑）；P5 待做 |

**术语**：

| 术语 | 含义 |
|---|---|
| 缺口（Gap） | 一条待取证命题；四态 open / resolved / blocked / inconclusive |
| 收割（harvest） | 把子代理结果里的 next_steps / limitations 转成缺口并更新状态 |
| 注入（injection） | 派发前把当前缺口段拼进子代理提示；`CLOUDAGENT_GAP_INJECTION` 可关 |
| 评估器（evaluator） | 一条"该继续还是该停"的独立规则；弃权 = 返回 None |
| 折叠（fold） | 把多个评估器的决策按优先级收敛成唯一决策的纯函数 |
| 域（domain） | sql / log / code 三个取证方向，对应一个只读子代理 |
| Φ / g_cap | 论文术语：语义判定（continue/complete/blocked）/ 资源上限（0/1），两者独立 |
| HYBRID | 独立核查的调度策略：信 continue、只核查终态、按间隔抽查 |
| 单写者 | 某份状态只有一个组件能写；多写者时最终状态由调用顺序决定 |
| 快慢分层 | 确定性判定（关键词、配额、传播）不走 LLM；可疑项才走 LLM |

---

## 附录 A：本仓代码锚点索引

| 位置 | 说明 |
|---|---|
| `diagnosis/session.py::decide()` | 停止决策（已改为评估器链）；原五条 if-else 语义见 docstring |
| `diagnosis/evaluators.py` | 五个评估器 + 注册序 = 判定顺序 |
| `query/stop_decision.py` | 通用协议 + 折叠纯函数 |
| `diagnosis/models.py:601` | `Gap` 定义（阶段 1 已加 `source_domain`） |
| `diagnosis/domain_gate.py` | **新增**（阶段 1）：域闸三档判据 + 域配额 + 域链 |
| `diagnosis/runtime_session.py::domain_gate()` | **新增**（阶段 1）：独立域链，与会话链互不影响 |
| `diagnosis/assessor.py` | **新增**（阶段 2）：独立核查（三档策略 + 64k 尾部截断 + 四种结论） |
| `diagnosis/runtime_session.py::bump_state_revision()` / `is_stale()` | **新增**（阶段 2）：状态版本；只在语义推翻时推进 |
| `tool_system/tools/agent.py::_with_current_state()` | **新增**（阶段 2）：「已确认 / 仍待取证 / 预算余量」三块注入段 |

| `tool_system/tools/agent.py:790` 附近 | 域闸插入点（`decide()` 之后、`begin_delegation` 之前） |

| `diagnosis/runtime_session.py:356` | `harvest_gaps()` 收割逻辑；`_actionable` 结构化门槛在 374-382 |
| `diagnosis/runtime_session.py:115` | `gap_summary()` 会话级快照（无域维度） |
| `diagnosis/text_match.py:45` | `TERM_EQUIVALENTS`（同时影响评分与生产判定） |
| `tool_system/tools/agent.py:646` | `_agent_call` 唯一派发点 |
| `tool_system/tools/agent.py:720` | 只有 `budget_exhausted` 硬停且仅诊断域 |
| `tool_system/tools/agent.py:133` | `_with_open_gaps` 注入段（纯字符串拼接） |
| `tool_system/tools/agent.py:183` | `_diagnosis_stopped_result` 结构化终止（payload 契约） |
| `context_system/microcompact.py:48` | 可压缩工具白名单（不含取证工具） |
| `services/context_collapse/trigger.py:184` | `CompositeTrigger` any/all |
| `context_system/prompt_assembly.py:612` | `cache_control` 分组标记（前缀稳定性） |
| `query/token_budget.py:22` | 另一套决策词汇 |
| `hooks/registry.py:27` | `RegisteredHook` 只有 `registration_order` |
| `diagnosis/evaluation/executors.py:277` | `LiveExecutor` 两种派发模式 |
| `diagnosis/evaluation/runner.py:350` | 开关泄漏守卫 |
| `diagnosis/evaluation/cost.py` | **新增**（阶段 0）：usage 键名归一与 token/cache 聚合；`available=False` 表示"不可得"而非 0 |
| `diagnosis/runtime_session.py`（`decision_log` / `gap_events`） | **新增**（阶段 0）：终止原因与缺口迁移的采集口 |


## 附录 B：参考实现锚点索引

见 §2.4 的十五行表格（`agent-core@0ab5913` 与 `jiuwenswarm@master`）。

## 附录 C：与其他文档的关系

| 文档 | 定位 |
|---|---|
| 本文 | **总纲**：为什么改、改什么、做到什么程度算完成、按什么顺序 |
| `diagnosis-orchestration-refactor.md` | **过程材料**：源码锚点逐条核对结果、外部材料阅读笔记、阶段性验收记录 |
| `docs/architecture.md` 等 | 仓库原有文档，本次不改动其约定 |
