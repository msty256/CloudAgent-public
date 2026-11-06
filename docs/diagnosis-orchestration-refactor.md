# 诊断编排改造（交接提示词 v3）· 核对报告与分期进度

> **本文是过程材料**：源码锚点逐条核对、外部材料阅读笔记、阶段性验收记录。
> **总纲（为什么改、改什么、做到什么程度算完成、按什么顺序）见
> [`diagnosis-redesign.md`](./diagnosis-redesign.md)**——那份不依赖代号，可独立阅读。

> 仓库：`CloudAgent-public`，基线提交 `0e48a58`
> 环境：Windows + Python 3.13.12（托管 venv），`tests/diagnosis` 基线 **538 passed / 25 skipped / 0 failed**
> 本文按交接提示词 v3 的 §4（锚点核对）与 §7（分期验收）组织，A1 完成后即时更新。

---

## 0. 环境与基线

### 0.1 依赖缺口（会伪装成逻辑缺陷，需先排除）

干净环境直接跑 `tests/diagnosis` 会出现 **1 个看起来像"缺口机制失效"的失败**：

```
tests/diagnosis/test_gap_orchestration.py::TestMainLoopContinuesAfterStop::
    test_loop_finishes_after_budget_stop
    assert runtime.session.delegations_used == 1  →  实际 0
```

根因不是编排逻辑，而是**缺包**：`Agent` 工具加载子代理定义时抛 `ImportError`，
被映射成模型可见的 tool_result 文本 `Error: No module named 'yaml'`（后续依次是
`jinja2`），于是**第一次派发根本没发生**，`delegations_used` 自然是 0。

补齐：`pytest`、`pytest-asyncio`、`PyYAML`、`jinja2`、`python-frontmatter`、
`pathspec`、`sqlglot`、`psycopg[binary]` 后基线全绿。

> 记这一条是因为它会污染后续所有"A 阶段必须全绿"的判断：**先验环境，再怀疑代码**。

### 0.2 §7 要求的基线指标：未采集

`§7 基线` 要求留档"委派数 / token / 终止原因分布 / 长案例 gaps_resolved / cache 命中率"。
这些需要 `diagnosis/evaluation/runner.py` 接真实模型跑 case 集，本环境没有模型凭据，
**尚未采集**。它同时是 A1 的回归基准与 P4.5 对照实验的起点，建议在有凭据的机器上补跑：

```bash
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync --variant gaps-on
```

---

## 1. §4 源码锚点核对

判定口径：**一致** = 行为与描述相同（行号允许小幅漂移）；**补充** = 提示词未提但影响方案；
**不符** = 描述与实际不一致。

| 锚点 | 提示词结论 | 实测 | 判定 |
|---|---|---|---|
| `diagnosis/session.py::decide()` | 五规则有序状态机，语义与预算耦合 | 改造前 242–278 行，逐字一致（含 ④ 的 `and not recent_open_ids` 冗余条件）；预算规则在最前，语义规则在后 | 一致 |
| `query/token_budget.py` | `COMPLETION_THRESHOLD=0.9`、`DIMINISHING_THRESHOLD=500`、自有 `ContinueDecision`/`StopDecision` | 22 / 23 行；48–55、58–62 行，`frozen=True`；与诊断域词汇互不相通 | 一致 |
| `tool_system/tools/agent.py` | 只有 `budget_exhausted` 硬停且仅对诊断域，其余 advisory | `_agent_call` 646 行起；713 行调 `decide()`；720–721 行判定 `reason == "budget_exhausted" and is_diagnosis_agent(...)`；722–725 行其余只 `logger.debug` | 一致 |
| 同文件 `_with_open_gaps` / `gap_injection_enabled` | 纯字符串拼接，净化写死在函数里 | 123 / 133 行；净化常量 100–103 行（5 条 / 200 字 / 1000 字总长）；`prompt + block` 于 180 行；拼接点在 736–737 行 | 一致 |
| `diagnosis/runtime_session.py::harvest_gaps()` | 证据关键词覆盖→resolved；resolved 不可回退、blocked 无解除路径 | 356 行起；417–429 行只把 `open` 改成 `resolved`，全仓无任何"回退/解除"写入点 | 一致 |
| `diagnosis/models.py::Gap` | 字段 `gap_id/statement/status/restatements/evidence_refs`，无 `source_domain` | **601 行**（提示词 ~588）；字段另有 `note: str = ""`（613 行）；确认无 `source_domain` | 一致（行号漂移 +13） |
| `diagnosis/text_match.py` | `TERM_EQUIVALENTS` 同时影响评分与生产判定 | 45–54 行；20–22 行"增补纪律"注释在 | 一致 |
| `diagnosis/evaluation/runner.py` + `test_ab_experiment.py` | gaps-on/off 变体 + 开关泄漏守卫 | variant 校验 236–247 行；泄漏守卫 350–352 行（`gaps-off` 且 `injected_dispatches>0` 即 raise） | 一致 |
| `tests/diagnosis/test_gap_orchestration.py` decide 用例 | 75–116 行附近 | `TestDecidePolicy` 72–116 行 | 一致 |
| `context_system/microcompact.py` | 时间隙 60 分钟 + `keep_recent=5`，`COMPACTABLE_TOOL_NAMES` 不含取证工具 | 48–60 行名单（Read/Bash/Shell/Grep/Glob/WebSearch/WebFetch/Edit/Write）；66–68 行三个默认值 | 一致 |
| `services/context_collapse/trigger.py` | 触发链骨架已有，子触发全是被动反应式 | `CompositeTrigger` 184 行 any/all + 取最激进；`Emergency413Trigger` 153 行 | 一致（枚举不全，见 D3） |
| `context_system/prompt_assembly.py` | 为 cache 边界做过精细工作 | 612–625 行注释：`cache_control` 按 GLOBAL/SESSION/REQUEST 分组标记 + 动态边界块 | 一致 |
| `query/continuation_nudge.py` | 正则续跑检测，cap=3 | `MAX_CONTINUATION_NUDGES = 3`（14 行） | 一致 |
| `hooks/registry.py` | `RegisteredHook` 无 priority 字段 | 27–31 行只有 `event/config/source/registration_order` | 一致 |
| 根 `README.md` 贡献指南 | 受 pyproject 的 import-linter **分层契约**约束 | 见 D4 | **不符（范围）** |

### 1.1 补充与不符

**D2（补充，影响 C2 / B1b）** `harvest_gaps` 里有一道提示词未记录的**结构化门槛**
`_actionable()`（374–382 行）：命题必须含至少一个 ASCII 标识符 / 引号 token / 两位以上数字，
否则不入账。理由注释写的是"一次委派产出十几条'无法判断/未检查…'"，会把注入段淹没。
这对后续有直接影响：**C2 的"证据推翻→缺口回退"对纯中文叙述型缺口天然不生效**（它们从一开始
就不在账本里）；B1b 的"当前有效状态"段规模也受这条门槛约束。

**D3（不符，不影响结论）** `context_collapse/trigger.py` 实际有三个子触发：
`TokenThresholdTrigger`（token 占比）、`Emergency413Trigger`（上游报错）、`CompositeTrigger`（组合）。
**时间隙触发不在这个文件**，而在 `context_system/microcompact.py`。共同点确实是"量驱动 / 被动反应"，
没有内容结构感知——§6-C1 的判断成立，但"时间触发 + 413"的枚举不准确，改造时别找错文件。

**D4（不符，影响 A1 落点纪律）** `pyproject.toml` 里 import-linter **只有一条契约**：
`bootstrap/state.py` 不得 import 特性子系统（416–445 行）。**`diagnosis/` 与 `query/` 之间没有任何契约**。
也就是说"新增协议模块放 `query/`（通用层）"目前靠纪律，不靠闸门。
A1 因此补了一个 AST 级测试（`test_stop_decision.py::TestGenericLayerPurity`）兜住
"通用层不得反向依赖领域层"这条纪律；要真正变成闸门，得另加 import-linter 契约（未做的可选步）。

**D5（补充）** `GapSummary` 定义在 `diagnosis/session.py`（88–104 行），而 `gap_summary()`
是 `DiagnosisSessionRuntime` 的**方法**（`runtime_session.py` 115–131 行），不是会话方法。
§4 那行把两者写在一起，读的时候容易误以为缺口快照由会话计算——实际是会话层不持有缺口状态。

---

## 2. 需要决策的冲突：A2 的"域闸"与现有测试契约

§7-A2 的验收写的是：

> 单域 blocked：**该域派发被拦**、其他域照常（扩展现有多域用例）

但现有测试 `test_gap_orchestration.py::TestDispatchPolicy::test_blocked_only_is_advisory`
（427–440 行）把**相反**的行为写成了契约：

```python
# 第一个 code-diagnosis 委派产出 blocked 缺口
assert runtime.decide().reason == "blocked_only"
# 提示但不阻断：**换一个目标**继续同域取证
second = tool.call({"prompt": "查 B", "subagent_type": "code-diagnosis"}, context)
assert second.is_error is False
assert runtime.session.delegations_used == 2
```

两者不能同时成立，除非给域闸加前提。三个选项：

| 选项 | 规则 | 代价 |
|---|---|---|
| **A 严格** | 该域出现 blocked-only 就拦该域**一切**派发 | 必须改 `test_blocked_only_is_advisory`（改测试要单独说明理由）；"同一域换问题继续查"会被误伤 |
| **B 同目标（推荐）** | 只在"本次 objective 覆盖该域某条 blocked 缺口的关键词"时拦——即拦的是**用同一个问法死磕已知取不到的证** | 测试零改动；语义更贴 §6-D"单域死磕被掐死"；多一句关键词判定（确定性快路径，不走 LLM） |
| **C 缩到配额** | A2 只补 `source_domain` + 结构化 tool_result 通道，闸门只由 A3 的域配额触发 | 最小改动；但 `blocked_only` 仍然不产生行为（等于没解决 §4 那条"死路"） |

推荐 **B**：它同时满足 §5"harness 通过 tool_result 塑形模型下一步选择"与现有测试契约，
且不引入新的误伤面。**未获确认前不动 A2 的拦截规则**（只做无风险的 `Gap.source_domain` 归因也需先定这个，
因为域闸的判定函数签名由它决定）。

---

## 3. A1：停止决策协议 + 评估器链（已完成）

### 3.1 改动文件

| 文件 | 性质 | 内容 |
|---|---|---|
| `cloudagent_ext/query/stop_decision.py` | 新增 191 行 | 通用协议：`StopDecision{action,scope,hard,domain,reason,evaluator}`、`decision_tier()`、`fold_decisions()`（纯函数）、`StopEvaluator` Protocol、`EvaluatorChain` |
| `cloudagent_ext/diagnosis/evaluators.py` | 新增 160 行 | 领域侧：`DiagnosisStopContext` + 五个评估器 + `build_default_chain()` |
| `cloudagent_ext/diagnosis/session.py` | 改 | `decide()` 五条 if-else → 链上折叠；`SessionDecision` 增加 `evaluator` 字段（默认 `""`，向后兼容）；新增 `_stop_context()` |
| `tests/diagnosis/test_stop_decision.py` | 新增 292 行 | 折叠优先级、归因、单评估器、**与旧 if-else 的等价性表**、通用层纯净性 AST 检查 |

### 3.2 before / after

**before**（`session.py` 改造前 242–278 行）：判定顺序与预算检查写死在同一函数体，
加一条规则必须改函数体，且"谁做的这个决定"只能靠 `reason` 字符串反推。

**after**（`session.py` 252–303 行）：

```python
decision = _DEFAULT_CHAIN.evaluate(
    self._stop_context(total_delegations=total_delegations, gaps=gaps)
)
return SessionDecision(
    should_continue=decision.should_continue,
    reason=decision.reason,
    evaluator=decision.evaluator,   # 新增归因
)
```

链的注册序（`evaluators.build_default_chain()`）= 原 D4 的判定顺序，**这是语义等价的全部依据**：

```
budget_exhausted(hard) → gap_open → blocked_only → success_recorded → budget_available(兜底)
```

折叠规则：`hard` > 域级 > 会话级；同 tier 用稳定排序保注册序。`reason` 字符串逐字未变
（对外契约不变，`blocked_only`/`success_recorded` 的使用方无感）。

### 3.3 验收

```
tests/diagnosis/test_gap_orchestration.py + test_session.py   54 passed   ← decide 用例零改动
tests/diagnosis/test_stop_decision.py                         59 passed   ← 新增
tests/diagnosis/（全量）                              597 passed, 25 skipped
```

其中等价性用例把"改造前 if-else"逐字复刻成 `_legacy_decide()`，对
**缺口形态(6) × 预算(0/14/15) × 是否有成功结果(2) = 36 组状态**逐一比对 `(should_continue, reason)`，
并断言 `evaluator == reason`（署名与判定同源）。

### 3.4 范围收窄说明（需你知情）

§6-A 写的是"**三套决策词汇 → 一套协议**"。A1 实际只收敛了**诊断域**这一侧，
`token_budget.py` 的 `ContinueDecision/StopDecision` 与 `context_collapse` 的 `CollapseDecision`
**未动**——把它们并进协议要改它们的公开契约与既有测试（且 `token_budget` 的 `action` 是
Literal 字面量、与新的 `action` 语义重复），属于独立一步，建议作为 A4 单列。
协议本身已经能容纳它们（`scope=delegation` + `reason` 即够），所以这一步是纯收敛、不改设计。

---

## 4. 材料阅读结论（2026-10-28 补）

论文与两个参考仓已读。**这一节只记"改变方案"的东西**，不重复 §2.1 摘要。

### 4.1 论文里三处交接提示词没写、但直接影响设计的点

**① Φ 与 g_cap 的显式分离 → 我们的协议已经同构，不要再"优化"成三值枚举**

论文式(10)(11)：语义停止是 `Φ_t(ℳ_t) ∈ {continue, complete, blocked}`，资源上限是独立的
`g_cap(ℳ_t) ∈ {0,1}`，`T = inf{t : Φ_t ≠ continue ∨ g_cap = 1}`。

对照 A1 的实现：`reason ∈ {gap_open→continue, blocked_only, success_recorded}` 就是 Φ 的三值，
`hard=True`（`budget_exhausted`）就是 g_cap。**协议不用改**。记这一条是为了挡住后续"把 action
扩成 continue/complete/blocked"的冲动——那会把 g_cap 重新塞回 action，退回混在一起的老问题。

**② 结构感知归约是"先确定性、后模型"的两段式，不是"上更聪明的小模型"**

论文 2.2 第 2 条：code diff / 日志 / 表格先由**确定性**结构处理器归约，**归约不动了**才用模型摘要；
并且"重复的无效推理/工具调用模式"也在塌缩范围内。
→ 我们 C1 的处理器必须先做纯 Python 的结构化归约（SQL 行集按列聚合、日志按错误指纹聚类），
LLM 摘要只作为兜底档位。这条同样约束 C2：**确定性传播是快路径，LLM 只在"可疑"时介入**。

**③ 实验分桶的统计强度：作者自己都不下强结论**

SWE-bench 按修复时长分四桶，但 **1–4h 只有 42 例、>4h 只有 3 例**，作者明说"不单独从 >4h 行下强结论"，
且三处声明这是 "systems-level interpretation rather than a controlled causal claim"。
→ 我们的 case 集规模远小于此，**P4.5 一律不做分桶统计**，只做"每臂 10 例结论级抽查"。

### 4.2 agent-core（pinned `0ab5913`）里"值得抄的具体机制"

| # | 位置 | 机制 | 我们的落点 |
|---|---|---|---|
| 1 | `harness/goal/schema.py:167-182` | `GoalRecord` 有 `revision` / `attempt_count` / `last_assessment` / `last_stop_reason` | B1a：我们的 session 缺 revision 与"上次判定"，缺口状态段无法判断新旧 |
| 2 | `harness/goal/schema.py` | `GoalStatus(active/paused/completed/blocked)` 与 `GoalAssessmentStatus(continue/complete/blocked)` **两套状态分开** | 缺口的 `status`（open/resolved/blocked/inconclusive）是"状态"，而"这次判定说了什么"应另存一列（B1b 的状态段要用） |
| 3 | `harness/goal/schema.py` | `GoalStopStrategy = agent_report \| transcript \| hybrid` | **B2 的三种策略原型**，见 4.3 |
| 4 | `harness/goal/evaluation.py:155-210` | HYBRID 八条规则：信任 CONTINUE、只核查 COMPLETE/BLOCKED、`verification_interval` 到了就抽查一次 CONTINUE、冲突以 transcript 为准、transcript 不可用则保守回落 continue | B2 直接照这个语义实现，**别做成"每次全量核查"**（成本会爆） |
| 5 | `harness/goal/evaluation.py:264-270` | `should_spot_check`：`attempt_count > 0 and attempt_count % interval == 0` | B2 的抽查节奏 |
| 6 | `harness/goal/evaluation.py:289-336` | `_apply_hard_limits`：**只有 CONTINUE 能被硬限制推翻**，命中后产 `BLOCKED + evidence="max_attempts_exhausted: n/m"` | A3：域配额耗尽也应产出**可读证据字符串**，而不是只给一个 reason 枚举 |
| 7 | `harness/rails/task_completion_rail.py:746-766` | 轮次前后校验三条件：`status ∈ allowed` ∧ `goal_id` 相等 ∧ `revision` 相等，任一不符则**丢弃本轮结果** | B1a 的判定函数就是这个形状 |
| 8 | `harness/goal/manager.py:179,196,217-221` | **in-flight 期间 bump_revision=False**；idle/BLOCKED 恢复时才递增；resume 时若正在跑则保留 revision | ★ B1a 的关键细节：naive 实现（每次改目标就 ++）会把**正在飞行的委派结果全部作废**，反倒丢掉有效证据 |
| 9 | `harness/rails/AGENTS.md` | priority 100→70 梯队；"**同一个数字排两件事：init 顺序与回调链顺序**"；同 priority 靠稳定排序保注册序 | hooks 补 priority 时，注册序与执行序必须由同一个数字决定（我们现在的 `registration_order` 只排了后者） |
| 10 | `core/context_engine/schema/config.py:11-22` | `CompressionRecallConfig{enabled, chunk_size_tokens=3000, chunk_overlap_tokens=300}` | C1 的句柄存储参数起点 |
| 11 | `.../forked/compressor/base.py:717-745` | 归档失败 → **不留 recall marker**，继续无召回（"不传播"原则的落地）；摘要里带 `[[COMPRESSION_RECALL: id=…]]`；`ContextEngineConfig.enable_reload` 监听模型输出的 `[[HANDLE:xxx]]` 自动回灌 | C1 的 offload/召回成对设计：**句柄先落库成功，才允许把原文替换成句柄** |
| 12 | `rails/context_engineer/context_processor_rail.py:52-131` | 处理器按 `(processor_key, config)` 成对注册，`priority=85`，按键 add-or-replace | C1 的触发链按同样方式插拔，而不是加 if |
| 13 | `symphony/flow/engine.py` | ingest → distill（`min_successes`、`min_pack_success_rate=0.8`）→ `sanitize_distilled_text` 脱敏 → `PackageReviewGate.review` → **versioned recipe** → prepare_install | E 阶段的入库卫生条件（success-only / 评审门 / 脱敏 / 版本化）**已有可直接对照的实现**，只是暂不启动 |
| 14 | `agent_teams/workflow/engine/primitives.py`（2173 行） | 编排算子就是普通 async 函数库（`budget/parallel/pipeline/agent/human` + 内部 `_check_budget`） | 我们**不该**造调度器——与 §5 结论一致，再确认一次 |
| 15 | `jiuwenswarm/agents/swarm/DESIGN.md`（**在 `master` 分支**） | 声明式装配三件套 + "属性/环境/句柄"三问 + skill 可见性单写者 | 见 4.5 |

### 4.3 对交接提示词的两处修正

**修正 1（B2 的形态）** §6-B 说 B2 是"独立完成核查（无工具、temperature=0、64k 尾部截断、
interrupt 轮跳过——照抄 jiuwen assessor 四件套）"。这四件套描述的是 **assessor 的执行形态**
（已核实：`task_completion_rail.py:64` 的 `_ATTEMPT_CONTEXT_MAX_CHARS=64_000`、
`:694` 的 `temperature=0.0`、`:538-546` 的 interrupt 跳过）。但 **jiuwen 的关键不在形态，在调度**：
`GoalStopStrategy` 默认是 **HYBRID**，规则是"信任 CONTINUE、只核查终态、按 interval 抽查"。
照抄四件套而不照抄调度，B2 会变成"每轮都花一次 LLM 调用"——**成本翻倍且收益不明**。
→ B2 按 HYBRID 语义实现，并保留 `agent_report`（=现状）与 `transcript`（=全量核查）两个可选臂，
这样 P4.5 才能把"核查策略"本身作为一个实验变量。

**修正 2（B1a 的陷阱）** §6-B1a 只说要"携带 session revision、收割时校验"。缺了 in-flight 规则
（上表 #8），实现出来会把正在执行的委派结果全部判为陈旧——**症状是"改目标后所有证据都丢了"，
而日志里一切正常**。这条必须写进 B1 的实现约束。

### 4.4 声明式装配的三问判定（`swarm/DESIGN.md` §6）

这份文档解决的是"一个字段该从哪来"，对我们**不当下的阶段**，但有两处直接可用：

**① 三问判定（原表）**

| 类别 | 判据 | 去向 |
|---|---|---|
| **属性值** | 是 `config.yaml` 里的 harness 设定吗？换请求不变 | `params`（构建期烘焙） |
| **环境值** | 随请求 / 会话 / 成员动态变化吗？ | `context`（运行时注入） |
| **基础设施/句柄** | 既非设定也非构造参数 | 不建模，工厂直读 |

原文的关键洞察："**`ctx.config` 是「伪装成环境的属性源」**"——所有由 config 派生的构造参数本质是
**属性**，应该由构建期烘焙进 spec，而不是在运行期从 context 里读。

→ 直接落到 **B1a**：注入段的净化参数（条数上限 / 单条字长 / 白名单）属于**属性**，
应该走配置并在装配期烘焙成值，**不要**在 `_with_open_gaps` 里每次读 env。
我们现在的 `gap_injection_enabled()` 是每次调用读 env——那是 A/B 开关，属于实验变量，可以留；
但净化参数不是。

**② 单写者原则（§11）**

两份 `skills-visibility.json` 各有**唯一写者**，理由写得很直白："曾经三处各播一次，语义碰巧一致
才没出事；任一处改播非空 allow，胜负就变成由调用顺序决定。"并配了回归护栏
（`test_platform_declares_no_team_scope_skill_visibility_seeder`）。

→ 落到 **C2**：缺口状态的写入方现在有两个——`harvest_gaps()`（收割证据）和（计划中的）
`propagate_invalidation()`（回退/解除）。**必须只有一个写者**，或者用一个显式的
`GapStore` 独占写入、两个调用方都只是"提交变更请求"。否则"回退"与"收割"并发时
谁是最终状态由调用顺序决定——正是 HLD 帖描述的失败模式。

### 4.5 没读到的（已无阻塞项）

- `agent_teams/workflow/engine/primitives.py` 只读了函数清单与 `_check_budget` 一带，未逐算子细读
  （结论只要"算子是用户态库"，已够）。
- 论文 §5 Limitations 已读。四条待发展方向里"Goal Mode 扩展到**层级化目标**"与我们最接近——
  论文没有多域并行诊断场景，**`scope=domain` 是我们要自己走的一步**。
- 路径坑：`jiuwenswarm/agents/swarm/DESIGN.md` 只在 **`master`** 分支存在，`main` 上是 404；
  仓库浅克隆会 `early EOF`（`--depth 1` 抓 GitHub 不稳），直连 raw 反而可靠。

---

## 5. 分期计划

排序原则：**先能度量（P0）→ 再把"停得对不对"做实（P1/P2）→ 再动上下文（P3）→ 最后做会改变
结论的传播（P4）→ 才谈统计结论（P5）**。每期都有"可宣称什么"的边界，避免把机制效果说成统计效果。

| 阶段 | 目标（一句话） | 主要内容 | 出口标准（可宣称） | 规模 | 依赖 |
|---|---|---|---|---|---|
| **P0 度量地基** | 让"效果"第一次可被测量 | 固定依赖清单（§0.1 的坑）；离线 stub provider 跑固定 case 集，落盘：委派数 / 终止原因分布 / 缺口流转计数 / 注入长度分布；token 与 cache 命中率标记为"需真实模型" | 同一 commit 连跑两次结果一致；基线 JSON 入库 | 小 | — |
| **P1 Φ 落地（A1✅ + A2 + A3）** | 停止判定可归因、且**按域**生效 | A2：`Gap.source_domain` + `domain_gate()` + 结构化 tool_result；A3：域配额评估器（`_apply_hard_limits` 式，带证据串） | 能回答"这次为什么停、停在哪个域"；单域停不误伤其他域 | 中 | P0 |
| **P2 状态可信（B1a/B1b/B2）** | 让 Agent 每轮看到的是**当前有效状态**，不是历史堆 | B1a revision（含 in-flight 规则）；B1b 注入段升级为"open 缺口 + 已确认结论 + 各域余量"；B2 `GoalStopStrategy` 三策略 + HYBRID 默认 | 陈旧写入计数=0（结构保证）；"独立核查 vs 关键词判定"分歧率报告 | 中 | P1 |
| **P3 上下文（C1）** | 长案例不再因取证结果爆上下文 | 结构处理器（确定性归约优先）+ `ev:` 句柄存储 + 按需召回（marker 模式） | cache 前缀稳定、命中率不回退；长案例子集对照 | 大 | P0（token 度量先行） |
| **P4 证据失效传播（C2）** | 被推翻的结论不再残留 | resolved→open(待复核) 沿 `evidence_refs` 回退；blocked→open 解除；回退后再 resolved 须过 B2；**缺口状态改由单一写者（`GapStore`）独占**，收割与回退都只提交变更请求（见 4.4②） | 两个新用例全绿；回退次数与"回退后再 resolved 一致率"可统计 | 中 | P2、P3 之后独立成臂 |
| **P5 对照实验（P4.5）** | 把机制效果与统计效果分开说 | 分臂 Baseline / A / A+D / A+B / C2，一次一个变量 + 开关泄漏守卫；每臂 10 例**结论级**抽查 | 产出一份"哪些是机制保证、哪些有统计支持"的报告 | 中 | P1–P4 |
| **P6 可选/延后** | 不做也不影响主线 | E 经验库（L2 schema + symphony 式卫生条件）、F 记忆五维评分、hooks priority、A4 三套词汇收敛 | 各自独立小交付 | 小 | P5 结论 |

### 5.1 关键取舍（写在前面，避免中途摇摆）

1. **P1 之前不碰 C1**：压缩会改变 token 与上下文长度，P0 没度量之前动它，等于把尺子先改了。
2. **P2 的 B1b 与 P1 的 A2 是同一份数据的两种用法**：A2 需要"域维度"，B1b 需要"域内有效结论"，
   两者共用 `Gap.source_domain`。所以 A2 必须先把域归因做实，B1b 才不用返工。
3. **P4 的 C2 依赖 B2**："回退后再 resolved 须经独立核查"这句话没有 B2 就是空话。
4. **不做**：全量依赖图、独立调度器/仲裁器、DEFER 域暂停、整体移植 Rail——理由见 §6 的"明确不做"，
   读完参考仓后这几条更确信（`primitives.py` 2173 行就是普通 async 函数库，jiuwen 自己也没造调度器）。
5. **A2 的拦截规则仍需决策**（本文档 §2 的 A/B/C 三选项）。读论文后推荐 **B 同目标版**：
   论文的 `Φ=blocked` 是**任务级**判定，我们是**域级**，粒度更细——"blocked"意味着"这个问法推进不了"，
   而不是"这个域死了"。同目标拦截恰好是这个语义的最小落地，且不动现有测试契约。

### 5.2 P0 怎么做（已确认 live 可用，2026-10-29 修订）

> 早先写的"本环境没有模型凭据 → 只能跑离线 stub"**判断错了**。本机
> `~/.cloudagent/config.json` 里 `default_provider=deepseek` 且有可用 key
> （ModelScope 端点，`deepseek-ai/DeepSeek-V4.1-Flash-1017`），`--mode live` 可以真跑。
> 下面这节替代原来的"离线基线"。

**① `--dispatch` 决定你到底在测什么（这条最容易踩）**

`LiveExecutor._ensure_ready()`（`evaluation/executors.py:277-330`）两种模式装配完全不同：

| 模式 | `load_agent_tools` | registry 里有什么 | 走不走 `_agent_call` |
|---|---|---|---|
| `direct`（**默认**） | `False` | 只有 `sql-diagnosis` 的工具 | **不走** |
| `main` | `True` | 只保留 `{Agent, Read, Grep, Glob, Skill, TodoWrite}` + 全量主 Agent 提示 | **走** |

缺口注入、`decide()`、域闸全都在 `_agent_call` 里。所以**默认的 `direct` 模式根本测不到这次改造**——
它的输出只反映"子代理单独干活"的能力。**基线必须用 `--dispatch main`**。

旁证：`direct` 下 `injected_dispatches` 恒为 0，runner 会在对比报告里打
"treatment 未施加（两臂 injected_dispatches 均为 0）"。这条守卫恰好能暴露"跑错模式"，
P5 复用它即可。

**② case 库存（38 例）**

```
sql: 14   code: 7   log: 6   cross: 6   sync: 5   （另有 routing/ 子目录）
```

外部依赖：`sql` / `sync` 需要 `cloudagent_sim`（上游）与 `cloudagent_sim_downstream`（下游）
两个 Postgres；**`code` 域不需要**——它诊断的是本仓代码
（如 `code-001` 问 `InvestigationSession / SessionBudget` 是否在派发链路上生效）。
→ **smoke 一律用 `code` 域**，最快且最贴当前改造。

另注：`_ensure_ready()` 硬编码按 `sql-diagnosis` 装配（`register_sql_diagnosis_tools`），
DB 装配失败会直接抛 `DB 工具装配失败`——那是环境问题，不要误判成编排缺陷。

**③ 三级跑法（每级都给结论再往上走）**

```bash
# L1 smoke：1 例、main 模式，确认整条链路通（预计 1–3 分钟 / 单例）
python -m cloudagent_ext.diagnosis.evaluation.runner \
  --mode live --dispatch main --domain code --max-cases 1 --timeout-per-case 180

# L2 估成本：同域 3 例，看 model_calls / elapsed / delegations 量级，估算全量代价
python -m cloudagent_ext.diagnosis.evaluation.runner \
  --mode live --dispatch main --domain code --max-cases 3 --repeat 2

# L3 基线入库：全量 38 例，两臂各跑一次（P5 的 Baseline 臂）
python -m cloudagent_ext.diagnosis.evaluation.runner \
  --mode live --dispatch main --domain code --variant gaps-on  --repeat 2
python -m cloudagent_ext.diagnosis.evaluation.runner \
  --mode live --dispatch main --domain code --variant gaps-off --repeat 2
```

**④ 基线要落盘的指标（从 `CaseRun.meta` 直接取）**

`executors.py:390-400` 已经记了 `model / elapsed_sec / model_calls / tool_calls /
main_tool_calls / sub_tool_calls / delegations`；加上 runner 侧的 `injected_dispatches`、
`gaps_total / gaps_resolved`，需要补的只有两项：**终止原因分布**（`decide().reason` 直方图）
与 **token（input/output 分开）**——后者要确认 `_RecordingProvider` 是否已捕获 usage。

**⑤ 环境前提：跑 live 需要完整依赖**

当前这台机器的 venv 只装了跑单测的最小集（pytest / PyYAML / jinja2 / sqlglot / psycopg），
**跑 live 会缺 `httpx` / `litellm` / `openai` 等**（`providers/runtime.py` → `auth/codex_oauth.py`
第一行就 import httpx）。要么 `pip install -e .` 装全套，要么按需补
`httpx openai litellm`。**单测能过 ≠ live 能跑**，这两套依赖要分开验。

### 5.3 现在的风险

| 风险 | 影响 | 处置 |
|---|---|---|
| case 集只有 38 例（单域更少：code 7、sync 5） | 任何比例型统计都不可信 | P5 只做结论级抽查，不做分桶/显著性；跨域聚合时按域分层报告 |
| `sql` / `sync` 依赖 `cloudagent_sim` 两个 Postgres | 该两域 live 可能大量 crash，看起来像缺陷 | 先只跑 `code` 域；DB 就绪后再补 |
| 跑错 `--dispatch` 模式 | 测到的不是缺口编排（见 5.2①） | 基线一律 `--dispatch main`，并用 `injected_dispatches>0` 自检 |
| 每次 live 都烧 token，且单例可达 180s | 全量 38 例 × 2 臂 × repeat 2 成本不低 | 先 L1/L2 估单价再决定全量规模，别一上来就全量 |
| 域维度是新东西（论文无此场景） | A2/A3 没有现成参照，只能自证 | 用 P1 的出口标准（单域停不误伤）当唯一闸门 |
| 会话级 `revision` 与委派并发 | B1a 的 in-flight 规则若写错，症状隐蔽 | 照 manager.py 的三态（in-flight / idle / resume）实现并补并发用例 |

---

## 6. 未完成 / 下一步

| 项 | 状态 |
|---|---|
| §2 论文与参考帖 | **已读**（论文 HTML 全文 + §2.1 内联摘要） |
| §3 参考仓 | **已读**：`agent-core@0ab5913`（Rails 规约 / Goal Mode / context engine / symphony / primitives）+ `jiuwenswarm@master` 的 `agents/swarm/DESIGN.md` |
| P0（度量地基） | **T0.1–T0.6 已完成**（详见 `proposals/phase-0-measurement.md` §10）；T0.7 跑基线 / T0.8 冻结未做 |
| A1 | **已完成**（§3） |
| A2 | **已完成**（阶段 1：默认 `same_target` 三档实现，含域配额），见 `proposals/phase-1-stop-decision-domain.md` §12 |
| A3 / B1 / B2 / C1 / C2 / P5 | B1a / B1b / B2（阶段 2）与 A3（阶段 3：结构归约 + 句柄 + 召回）**已实现**；C1 / C2 / P5 未开始 |




