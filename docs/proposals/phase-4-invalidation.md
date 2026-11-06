# 阶段 4 提案：证据失效传播

> 对应总纲 [`diagnosis-redesign.md`](../diagnosis-redesign.md) §4.3 与 §5「阶段 4」
> 前置：阶段 2（状态可信）已完成——回退后的再次 resolved 必须过独立核查
> 状态：**T4.1–T4.4 全部实现（2026-11-03）**；
> 过程中修正了一处提案未预见的协议阻塞（`conflict` 的跨轮引用被模型层丢弃，见 §6）
> 提案日期：2026-10-30 ｜ 决策更新：2026-10-30 ｜ 执行：2026-11-03

---

## 0. 一句话目标

让缺口状态机第一次能**往回走**：被后续证据推翻的 `resolved` 退回 `open（待复核）`，
有覆盖性证据到达时 `blocked` 也能解开——但**不判定谁对谁错**，只降低可信度。

## 1. 起点：两个"错误终态"

- `resolved` 一旦写入，全仓没有任何一处能把它改回去；
- `blocked` 一旦置入（`limitations` 收割时直接就是 blocked），除了新的 `resolved` 之外没有解除路径，
  而解除路径本身又要求它是 `open` 才会被关键词检查（`runtime_session.py:418-420` 的
  `if gap.status != "open": continue`）。

后果就是 HLD 帖描述的那个失败形态：**证据被推翻，但基于它的结论仍然挂在缺口上，且看起来一切正常。**

## 2. 三个已存在的零件（这是本阶段能做得干净的原因）

核了代码，C2 需要的东西**大部分已经在仓库里了**，不需要新协议字段：

### 2.1 触发源：`Evidence.relation` 已支持"冲突"表达

`models.py:252` 有 `relation: list[dict[str, Any]]` 字段（`extend-evidence-semantics` 变更引入），
而 `arbitration.py:105-121` **已经在消费它**：

```python
for relation in getattr(evidence, "relation", []) or []:
    if str(relation.get("kind", "")) != "conflict":
        continue
    other = str(relation.get("with") or "")
    # → Conflict(kind="evidence_relation", ...)
```

也就是说子代理**已经可以**这样声明：

```json
{"evidence_id": "ev:sql:7", "observation": "...",
 "relation": [{"kind": "conflict", "with": "ev:sql:1", "why": "count 由 0 变为 5"}]}
```

**但它目前只进 `conflict_report()` 给人看，不回写缺口状态。** 这就是本阶段要接的口。

### 2.2 解析路径：`evidence_refs` 就是"证据 → 缺口"的边

`Gap.evidence_refs`（`models.py:612`）在判定 resolved 时被填入 evidence_id
（`runtime_session.py:428`）。所以"哪条证据支撑了哪个缺口的结论"这件事**已经记着**，
回退只需要反查这张表，**不需要建全量依赖图**。

### 2.3 回退原因的落点：`Gap.note` 字段

`Gap.note: str = ""`（`models.py:613`）已经存在且未被使用。回退原因写在这里，
**不新增第五种状态**——`open` 就是"待取证"，重试语义一致。

## 3. 一个必须讲清的边界：C2 不违反"不裁决"原则

`arbitration.py` 的策略写得很明确：**跨子代理冲突不裁决，只保证它被看见并写进报告**。
C2 会不会破坏这条？不会。

区别在于：

| | 裁决（不做） | 降级（要做） |
|---|---|---|
| 判断 | "ev:sql:1 对还是 ev:sql:7 对" | "这条结论现在有争议" |
| 动作 | 选一个保留、丢弃另一个 | 两个都保留，但把**依赖前者的缺口**退回待复核 |
| 依据 | 需要领域判断 | 只需要"存在冲突声明"这个事实 |

所以 C2 的输出是**可信度**，不是**胜负**。这也解释了为什么它能走确定性快路径：
检测冲突是结构匹配，不需要理解语义。

## 4. 两个必须先讲清的设计问题

### 4.1 震荡：回退必须有上限

不加约束会形成循环：

```
resolved ──冲突──> open ──重新取证──> resolved ──同一冲突──> open ──> …
```

每一轮都消耗委派预算，而且模型会一直被要求"重查同一件事"。这是**必须防的死循环**，
和现有 `restatements >= 2 → inconclusive` 是同一类保护。

方案：单缺口**回退计数**，达到上限（默认 2）后转 `inconclusive` 并在 `note` 写明
"证据反复冲突，已放弃自动收敛"。计数与 `restatements` 分开记——一个是"被复述"，一个是"被推翻"。

### 4.2 单写者：现在有两个写缺口状态的地方

`harvest_gaps` 是唯一写者（append / 改 status / 填 evidence_refs）。C2 要加第二个写者
（回退 / 解除）。参照 `swarm/DESIGN.md` §11 的教训——**两个写者时最终状态由调用顺序决定**。

所以引入 `GapStore`：状态只通过它的方法改，`harvest_gaps` 与 `invalidate` 都只是它的调用方。
这是**行为等价重构 + 加新能力**两件事，要分两步做（T4.1 先等价重构，T4.2 再加回退）。

---

## 5. 任务步骤

### T4.1 `GapStore`：单写者（行为等价重构，**测试零改动**）

**做什么**

1. 新增 `cloudagent_ext/diagnosis/gap_store.py`：

```python
class GapStore:
    def add(self, statement, *, domain, status) -> Gap          # 去重 + restatements 累加
    def mark_blocked(self, gap_id, *, why) -> bool
    def mark_resolved(self, gap_id, *, evidence_id) -> bool
    def mark_inconclusive(self, gap_id, *, why) -> bool
    # 阶段 4 新增：
    def revert(self, gap_id, *, why, evidence_id) -> bool       # resolved → open（待复核）
    def release(self, gap_id, *, why, evidence_id) -> bool      # blocked  → open
    def gaps(self) -> tuple[Gap, ...]
    def events(self) -> tuple[dict, ...]                        # 阶段 0 的 gap_events 落点
```

2. `harvest_gaps` 改为调 store 方法，**判定逻辑与顺序一字不动**（`_actionable`、上限 3、
   restatements→inconclusive 都保持）；
3. `runtime.gaps` 保留为只读属性（`store.gaps()`），避免外部代码直接 append；
   —— 注意 `executors.py:394`、`tasks_command.py:61` 都读 `runtime.gaps`，保持可读即兼容。

**验收**：`test_gap_orchestration.py::TestHarvest` 全部用例**不改一行**通过；
`gap_events` 内容与 T0.4 的采集口一致。

### T4.2 冲突 → 回退

**做什么**

1. 新增 `propagate_invalidation(runtime, parsed, *, conflicts=None)`：
   ```
   取本次结果的 conflict 声明（relation.kind == "conflict"，with=<evidence_id>）
     → 反查 GapStore：哪些缺口把 <evidence_id> 记进了 evidence_refs
     → 对这些缺口：resolved → open（待复核）
        note 写：f"证据冲突：{new_evidence_id} vs {old_evidence_id}；已退回待复核"
        记事件 {from: resolved, to: open, why: "invalidated"}
    ```
2. 调用点：`harvest_gaps` **之后**（同一把 runtime 锁内），只在 `status ∈ {success, partial}` 时跑；
3. 回退后 `open` 的缺口自然进入下一轮注入——**不需要额外触发**；
4. 回退计数 `revert_count` 存在 Gap 上（新字段，默认 0），达到上限转 `inconclusive`（§4.1）。

**验收**：新增用例——(a) 证据 A 支撑 gap-1 已 resolved；(b) 新结果声明 conflict with A；
(c) gap-1 变回 open 且 note 有原因；(d) 再 resolved 一次后又冲突两次 → 转 inconclusive。

### T4.3 覆盖性证据解除 blocked

**做什么**

把 `harvest_gaps` 里那段关键词覆盖检查的适用范围从 `open` 扩到 `open + blocked`，但**结果不同**：

| 原状态 | 证据全覆盖时 | 理由 |
|---|---|---|
| `open` | → `resolved`（现有行为不变） | 直接命中 |
| `blocked` | → `open`（**新增**） | 覆盖说明"前提可能已满足"，但"能查了"≠"已查清"；让它走正常流程，且再次 resolved 要过核查 |

**验收**：用例——blocked 缺口被证据全覆盖后变 open（不是 resolved），下一轮能正常 resolved。

### T4.4 回退后再 resolved 须过独立核查（与阶段 2 配对）

**做什么**

1. 回退过的缺口（`revert_count > 0`）再次 resolved 时，**强制**走 B2 核查
   （即使当前策略是 `agent_report` 或未到抽查间隔）；
2. 核查不过 → 保持 open，`note` 记"核查未通过"。

**为什么必须**：回退意味着这条结论曾经不可靠；用同一个关键词判定让它"再 resolved"一次，
等于什么都没改变。**这是快慢配对原则的落地**：传播走确定性快路径，收敛必须走核查慢路径。

**验收**：用例——回退缺口在 `agent_report` 档下再次 resolved 时，仍调用了一次核查。

---

## 6. 执行记录（2026-11-01 ~ 11-03）

### T4.1 `GapStore` 单写者：**完成**

新增 `cloudagent_ext/diagnosis/gap_store.py`（`add` / `add_existing` / `mark_*` /
`revert` / `release` / `gaps` / `events` / `resolved_claiming`）。

`DiagnosisSessionRuntime` 的 `gaps` / `gap_events` / `gap_event_seq` 从裸字段
改成**只读 property**，转发到 `gap_store`；`harvest_gaps` 全部改调 store 方法。

**提案说"测试零改动"，实际有 6 处要改**——提案写作时没注意到 `gaps` 一旦变成
只读视图，`assert rt.gaps == []` 与 `rt.gaps.append(...)` 就不能用了。改动如下：

| 位置 | 原因 | 改法 |
|---|---|---|
| `test_domain_gate` 两处 | 直接往 `gaps` 塞构造好的 Gap | 改用 `gap_store.add_existing()` |
| `test_gap_orchestration` 一处 | 同上 | 同上 |
| 三处 `== []` | tuple ≠ list | 改 `== ()` |
| `test_eval_metrics::test_events_are_capped` | 事件上限的真相源移到了 store | `monkeypatch` 目标从 `runtime_session._MAX_GAP_EVENTS` 改成 `gap_store.MAX_EVENTS` |

**行为等价**：语义（去重、`restatements` 累加、域回填、blocked 降级、
事件结构）逐条复刻；诊断域 725 个用例全绿。

### T4.2 冲突 → 回退：**完成**

新增 `propagate_invalidation(runtime, parsed) -> int`，在 `harvest_gaps` 末尾
**同一把锁内**、**收割之后**调用（顺序有讲究：先让本轮证据正常入账，再看它是否推翻早先结论；
反过来本轮刚核销的缺口会被自己推翻）。

只对 `status ∈ {success, partial}` 生效；`failed` 不推动状态变更。

### ⚠ 过程中发现一个**阻塞级**问题（提案未预见）

**触发源在生产路径上根本到不了。**

`DiagnosisResult.__post_init__` 的 `_collect_soft_warnings()` 会把"引用了本次结果里
不存在的 evidence_id"的 relation **直接丢弃**。而 `conflict` 的语义**天生跨轮**——
它说的是"这次观测和上轮证据冲突"，目标当然不在本次结果里。

后果：子代理即使按提案的写法声明了冲突，关系也会在模型层被清空，
`propagate_invalidation` 永远收不到信号，**而且不报错、日志里一切正常**。

更值得注意的是：仓库里本来就有一条用例把这个边界固化了，注释写着——

> "此处把该行为固化，将来若改协议（允许前向引用），这个用例会失败并提醒同步更新文档。"

**修法**：`_collect_soft_warnings` 对 `kind == "conflict"` 放行外部 id（只记 soft warning），
其余关系仍按原规则丢弃。

安全性：防编造的能力没削——下游是反查 `Gap.evidence_refs`，
编造的 id 匹配不上任何缺口，最多在冲突报告里多一条噪音。

**连带收益**：`detect_conflicts` 会遍历所有 entry 收集 id 再配对，所以关系保留后，
**跨子代理冲突第一次能被仲裁层直接报出来**——原先只能靠 `opposing_claim` 的文本启发式猜。

### T4.3 覆盖性证据解除 blocked：**完成**

`harvest_gaps` 的覆盖检查从 `status == "open"` 扩到 `open + blocked`，但结果不同：
`open → resolved`（原行为）、`blocked → open`（新增，走正常流程 + 将来仍需过核查）。

### T4.4 回退后再 resolved 须过核查：**完成**

`should_verify()` 新增 `forced` 参数（True 时无视策略）；`runtime.force_verify_reason`
作为"决定权在账本、触发点在 agent.py"之间的传话通道：

```
harvest_gaps: mark_resolved 且 gap.revert_count > 0
            → runtime.force_verify_reason = "invalidated_then_resolved"
_run_assessor: should_verify(..., forced=bool(force_verify_reason))
            → 核完（或 skipped）立即清空
```

**为什么必须一次性清空**：不清的话这条会话往后每轮都被强制核查，
成本翻倍而收益为零。用例 `test_clean_gap_does_not_force` 守着反向条件——
从没被推翻过的缺口不该被强制，否则"强制核查"等于全量核查。

### 阶段 4 收尾 + 阶段 5 的分臂开关（同日）

为了让阶段 5 能做单变量对照，两个新机制补上了独立开关
（`cloudagent_ext/diagnosis/switches.py`）：

| 开关 | 默认 | 关掉以后 |
|---|---|---|
| `CLOUDAGENT_CONTEXT_REDUCE` | `on` | 不做结构归约（回到改造前） |
| `CLOUDAGENT_EVIDENCE_INVALIDATION` | `on` | 冲突不回退缺口 |

`env_flag()` **只认明确真假写法**，认不出就退回默认——不猜。
猜错会让"我以为关了但没关"这类问题永远查不出来。

守卫用例 `tests/diagnosis/test_switches.py`（21 例）分两层：
语义（unset/truthy/falsy/无法识别）+ **生效**（关掉后机制确实不产生作用，
不是只看变量读到了）。


### T4.5 观测

**做什么**

meta 增加：`gap_reverts`（次数）、`gap_releases`（blocked 解除次数）、
`revert_then_resolved`（回退后再次 resolved 的次数）、
`revert_resolved_verified`（其中通过核查的次数）→ 两者之比即"回退后再 resolved 一致率"；
`oscillation_guards`（转 inconclusive 的次数）。

### T4.6 测试

| 类型 | 内容 |
|---|---|
| 必须零改动 | `TestHarvest` 全部、`test_session.py`、`test_stop_decision.py` |
| 新增 | `tests/diagnosis/test_invalidation.py`：回退三用例 + 解除两用例 + 震荡保护 + 强制核查 |
| 集成 | 一轮完整流转：resolved → 冲突 → open → 再取证 → resolved（过核查） |

---

## 6. 产出物

| 类型 | 路径 | 说明 |
|---|---|---|
| 代码 | `diagnosis/gap_store.py`（新） | 单写者 + 事件流 |
| 代码 | `diagnosis/models.py` | `Gap.revert_count: int = 0` |
| 代码 | `diagnosis/runtime_session.py` | `harvest_gaps` 改走 store；新增 `propagate_invalidation` |
| 代码 | `diagnosis/evaluators.py` / `assessor.py` | 回退缺口的强制核查钩子 |
| 测试 | `tests/diagnosis/test_invalidation.py`（新） | 见 T4.6 |
| 文档 | 总纲 §4.3 状态更新 | 完成情况 + 震荡上限定为几 |

## 7. 依赖关系

**硬前置**：阶段 2（B2 核查器存在）——否则 T4.4 无法实现，"回退后再 resolved 须核"是空话。

**软依赖**：阶段 1 的 `source_domain`（回退时能指出是哪个域的证据，日志更可读，但不是必须）。

**被谁依赖**：阶段 5（对照实验）——C2 是一个独立实验臂（开/关），
指标就是 §1 里那组：回退次数、一致率、震荡保护触发次数。

## 8. 决策点（三个）

### 决策点 1：`blocked` 被覆盖时回 `open` 还是直接 `resolved`

| 选项 | 含义 |
|---|---|
| **回 `open`（推荐）** | "能查了"≠"已查清"；让它走正常流程，且再次 resolved 要过核查 |
| 直接 `resolved` | 少一轮派遣，但把"前提满足"当成"结论成立"，等于放宽了口径 |

推荐回 `open`：blocked 的语义是"推进不了"，证据到达只说明"可以推进了"。

> **已定（2026-10-30）：回 `open`。** 再次 resolved 时同样要走核查（T4.4 对回退过的缺口一律生效）。


### 决策点 2：回退的执行时机

| 选项 | 含义 |
|---|---|
| **收割后同步执行（推荐）** | 与 harvest 同一把锁内完成，下一次注入立即生效；状态自洽 |
| 下次派发前惰性执行 | 省一次遍历，但状态会短暂不自洽（`/tasks` 显示的还是旧状态） |

推荐同步：本来就是一次列表遍历，成本可忽略；而"人看的视图与 Agent 用的状态一致"是明确要求。

> **已定（2026-10-30）：收割后同步执行**，与 `harvest_gaps` 同一把 `runtime.lock`。


### 决策点 3：震荡上限

| 选项 | 含义 |
|---|---|
| **单缺口回退 2 次后转 `inconclusive`（推荐）** | 与 `restatements >= 2` 对称；"同一件事被推翻两次"基本可以判为无法自动收敛 |
| 不设上限 | 会无限循环，每轮都烧预算 |
| 1 次就转 | 太急——证据偶尔冲突是正常的（比如数据在变） |

> **已定（2026-10-30）：单缺口回退上限 2 次，之后转 `inconclusive`**；上限可配
> （`CLOUDAGENT_GAP_MAX_REVERTS`，默认 2）。触发时 `oscillation_guards` 计数 +1，`note` 写明原因。


## 9. 风险与应对

| 风险 | 表现 | 应对 |
|---|---|---|
| **震荡烧预算** | 同一缺口反复 resolved↔open，每轮都派发 | 回退上限 2 → `inconclusive`；计数与 `restatements` 分开 |
| 误回退（冲突其实是表述差异） | 正常结论被反复退回 | 只处理**结构化声明**的 `kind == "conflict"`，不做文本语义推断；误判率进报告 |
| 单写者重构破坏现有行为 | `TestHarvest` 大面积红 | T4.1 只做等价重构，测试零改动通过后才进 T4.2 |
| 回退让"已确认"块变空 | 状态段看起来没进展，模型困惑 | 状态段里回退过的缺口标注"待复核（曾被推翻）"，与全新缺口区分 |
| `relation` 声明质量依赖子代理 | 子代理不写或乱写 | 不写 = 不触发（保守）；乱写的代价是误回退，靠上限兜底；后续可在协议里加示范 |
| 与 arbitration 的职责混淆 | 两处都在处理 conflict | 明确分工：`arbitration` 只产报告（人看），`propagate_invalidation` 只改状态（机用），**互不调用对方的输出格式** |

## 10. 工作量与顺序

| 步 | 规模 | 依赖 live | 备注 |
|---|---|---|---|
| T4.1 GapStore | 中 | 否 | 纯重构，风险最高（动的是核心路径），必须测试零改动 |
| T4.2 回退 | 中 | 否 | 反查 evidence_refs，逻辑简单 |
| T4.3 解除 blocked | 小 | 否 | 扩一个条件，注意结果不同 |
| T4.4 强制核查 | 小 | 否 | 复用阶段 2 的核查器 |
| T4.5 观测 | 小 | 否 | meta 字段 |
| T4.6 测试 | 中 | 否 | 回退/解除/震荡/强制核查 |

建议顺序：T4.1 → T4.3（简单，先验证 store 好用）→ T4.2 → T4.4 → T4.5 → T4.6。

## 11. 完成的标准（本阶段出口）

1. **旧结论不再残留**：证据冲突后，依赖它的缺口从 resolved 退回 open，`note` 有原因；
2. **blocked 能解开**：覆盖性证据到达后变 open，并能正常走到 resolved；
3. **不震荡**：同一缺口回退 2 次后转 inconclusive，`oscillation_guards` 可观测；
4. **回退后的收敛是可信的**：`revert_then_resolved` 与 `revert_resolved_verified` 的比值可报出。

至于"回退机制是否让诊断更准"——**本阶段仍不回答**，它是阶段 5 的独立实验臂（C2 开/关）。

---

## 12. 决策记录

| 时间 | 决策 | 影响 |
|---|---|---|
| 2026-10-30 | `blocked` 被覆盖时回 `open`，不直接 `resolved` | T4.3 的分支结果；再次 resolved 仍要过核查 |
| 2026-10-30 | 回退与收割**同步执行**（同一把锁） | T4.2 的调用点固定在 `harvest_gaps` 之后、锁内；`/tasks` 显示与状态始终一致 |
| 2026-10-30 | 单缺口回退上限 2（可配），超限转 `inconclusive` | T4.1 的 `Gap.revert_count` + T4.2 的保护分支；对应指标 `oscillation_guards` |

