# 阶段 0 提案：度量地基

> 对应总纲 [`diagnosis-redesign.md`](../diagnosis-redesign.md) §5「阶段 0」
> 状态：**T0.1–T0.6 已实现（2026-10-30）**；T0.7 跑基线、T0.8 冻结待确认
> 提案日期：2026-10-29 ｜ 决策更新：2026-10-29 ｜ 执行：2026-10-30（见 §10）

---

## 0. 一句话目标

**在改任何逻辑之前，先让"改得对不对"变成一组可复现的数字**：同一份代码、同一配置，跑两次能得到可比的指标；
并且确认评测走的是**缺口编排真正生效的那条链路**。

## 为什么必须第一个做

后面每个阶段都会改变 token 消耗、委派次数、停止时机。没有基线，
(a) 改完无法判断是变好还是变坏；(b) 连"改错了"都发现不了——因为指标本身也是改完之后才有的。
更实际的一点：现在报告里**没有 token、没有终止原因分布、`--repeat` 的聚合还是错的**，
这三样正是阶段 1、3、5 要依赖的度量。

---

## 1. 现状盘点（先确认我理解的和代码一致）

### 1.1 已经有的（不需要重做）

`CaseRun.meta`（`evaluation/executors.py:395-416`）已经采集：

```
model / elapsed_sec / model_calls / tool_calls / main_tool_calls / sub_tool_calls /
delegations / gaps_total / gaps_resolved / injected_dispatches /
dispatch_mode / agents_dispatched / tools_resolved / terminal
```

`_RecordingProvider.calls[]`（同文件 213-230）每次模型调用记了
`n / elapsed_sec / model / usage / finish_reason / tool_uses / content`
——**`usage` 原始字典已经在了**，只是没人聚合。

`run_payload` 已落盘：`run_id`（含 mode+variant+case 哈希）、`metrics`（六个比率）、
`experiment`（跨案例汇总）、`repeats`（多轮快照）、`results`（逐 case 明细含 `calls`）。

### 1.2 缺的（本阶段要做）

| # | 缺什么 | 证据 |
|---|---|---|
| 1 | **token 没聚合**（`calls[].usage` 有原始值，meta 里没有汇总字段） | `executors.py:395-416` 的 meta 无 token 键 |
| 2 | **cache 命中率没有** | 同上；`prompt_assembly.py` 打了 `cache_control` 标记，但没人测量效果 |
| 3 | **终止原因分布没有**（`decide().reason` 只在 `_agent_call` 里 `logger.debug`） | `agent.py:713-725` |
| 4 | **缺口流转历史没有**（只有 `gaps_total` / `gaps_resolved` 两个快照值） | `executors.py:403-404` |
| 5 | **`--repeat` 聚合是错的**：`_experiment_stats` 里 `delegations` / `gaps_total` / `injected_dispatches` 等取 `per_round[0]`，多轮时不聚合 | `runner.py:177-188` |
| 6 | **跑错腿没有提示**：`--dispatch` 默认 `direct`，而 `direct` 不经过 `_agent_call`，缺口注入恒为 0 | `executors.py:277-330`；`runner.py:350-352` 只覆盖 `gaps-off` 臂 |
| 7 | **依赖清单没固化**：单测要 PyYAML/jinja2/sqlglot/psycopg，live 要 httpx/openai/litellm，`PYTHONPATH` 要带 `.;extensions/lkb/src` | 本次实际踩过 |

---

## 2. 目标与非目标

**目标（本阶段出口）**

- 一次 live 运行结束，能从落盘产物里读到：**token（input/output/cache 分开）、终止原因分布、缺口流转、委派数、耗时**；
- 同一 commit + 同一配置跑两次，**指标可比**（比率一致，耗时可波动）；
- 基线数据入库，并明确标注"哪些指标本环境测不出来"。

**非目标（本阶段不碰）**

- 不改 `decide()` 的任何判定逻辑（A1 已完成，保持不动）；
- 不改缺口注入内容、不改上下文压缩、不加域维度（那是阶段 1/2/3）；
- 不追求"好看的指标"，本阶段只求**测得准、测得全、能复现**；
- 不给 `sql` / `sync` 域建数据库（见 §6 决策点 1）。

---

## 3. 任务步骤

八步，前五步是代码改动（纯离线可测），后三步要跑 live。

### T0.1 固化环境，让"能复现"成立

**做什么**

1. 新增 `requirements-eval.txt`（或 `docs/` 里一节）：列出跑测试与跑 live 各自需要的包，
   区分「测试必需」与「live 必需」，附 `PYTHONPATH` 设置说明（Windows 用 `;`，POSIX 用 `:`）；
2. 在总纲 §6 补一条"如何验证环境就绪"的自检命令（能构造 provider + 能 import 工具链）。

**为什么不写进 `pyproject.toml` 的 `dependencies`**：那会改变所有人的安装体积与 CI 时间；
评测依赖本来就该是可选的。

**验收**：按文档从零建 venv → `pytest tests/diagnosis -q` 全绿；按文档构造 provider 成功。

---

### T0.2 token 与 cache 采集

**做什么**

1. 新增 `cloudagent_ext/diagnosis/evaluation/cost.py`：
   ```python
   def summarize_usage(calls: list[dict]) -> dict
   # 返回 {input_tokens, output_tokens, cached_input_tokens, total_tokens,
   #       calls_with_usage, calls_without_usage, cache_field}
   ```
   逐项做**键名归一**（不同 provider 不一致）：
   - 输入：`input_tokens` / `prompt_tokens`
   - 输出：`output_tokens` / `completion_tokens`
   - 缓存：`cache_read_input_tokens` / `prompt_cache_hit_tokens` / `cached_tokens`
2. `LiveExecutor.run_case` 把结果塞进 `meta["usage"]`；
3. `_round_totals` 增加 token 求和（input/output/cache 分开），`_experiment_stats` 一并带出；
4. **关键约束**：认不出的 usage **不能静默当 0**——记 `calls_without_usage`，
   若某臂全为 0 则报告里显式写"token 不可得"，避免"看起来省了 token"的假象。

**验收**：单测用多组伪造 `calls`（OpenAI 风格 / Anthropic 风格 / 缺失 usage）覆盖；
一次真实 1 例运行后 `meta["usage"]["input_tokens"] > 0`。

---

### T0.3 终止原因分布

**做什么**

1. `DiagnosisSessionRuntime`（`runtime_session.py`，`@dataclass`）增加 `decision_log: list[dict]`；
2. `_agent_call` 在 `decide()` 之后追加一条：
   `{turn, should_continue, reason, evaluator, gap_open_count, blocked_count, total_delegations}`；
   —— 记录点必须在**原来只 `logger.debug` 的位置**，不改变控制流；
3. meta 带出 `decision_counts`（reason → 次数）与 `decision_log`（可按上限截断，避免报告膨胀）。

**为什么不用日志 grep**：日志在并发与多子代理下顺序不可靠，且报告要能离线重算。

**验收**：单测构造"连续三次派发、每次 decide 原因不同"的语境，断言 `decision_counts`；
既有 597 个测试不回归。

---

### T0.4 缺口流转历史（最小版）

**做什么**

1. `harvest_gaps` 里每次状态变化追加一条事件：
   `{gap_id, from_status, to_status, why, evidence_id?}`；`why ∈ {new, blocked, resolved, inconclusive}`；
2. meta 带出 `gap_events`（同样按上限截断）。

**为什么现在做**：阶段 4（证据失效传播）要统计"回退次数""回退后再 resolved 的一致率"，
但事件流的**采集口**必须在阶段 0 就存在——否则到时改动会同时动逻辑与埋点，分不清回归来自哪边。

**本阶段不做**：不新增 `resolved → open` 的迁移（那是阶段 4），只把**已有的四种迁移**记下来。

**验收**：单测覆盖 new / open→blocked / open→resolved / open→inconclusive 四条路径。

---

### T0.5 修 `--repeat` 的聚合缺陷

**做什么**

`runner.py:177-188` 里 `delegations` / `gaps_total` / `gaps_resolved` / `injected_dispatches` /
`main_tool_calls` / `sub_tool_calls` 都取 `per_round[0]`，只有 `_METRIC_KEYS` 那四个键做了 median/min/max。
`--repeat 2` 时这些数字**只是第一轮**，报告却看起来像总量。

**已定（2026-10-29）：采用 A，补聚合。** 实现方式：这些键与 `_METRIC_KEYS` 一致地给出
median / min / max，`series` 里保留每轮原始值；字段名不改，避免下游报告解析断裂。

- **A 补聚合**（采用）：这些键也进 median/min/max，`series` 里保留每轮值；
- **B 改名显式**（不采用）：保留"第一轮"语义，但字段改叫 `round1_delegations` 等——改动面更大，
  且历史报告与新报告字段名不一致，反而更难对比。

**风险**：`tests/diagnosis/test_evaluation_runner.py` 与 `test_ab_experiment.py` 可能断言了这些字段名，
改动会红——**这是唯一一处需要动既有测试的地方**，若发生我会单独说明理由与影响面。

**验收**：`--repeat 2` 的报告里，聚合字段与 `series` 一致；既有测试按选定方案处理。

---

### T0.6 跑错腿的自检（防"测了另一条链路"）

**做什么**

在 `run_evaluation` 里加一条显式检查：当 `mode=="live"` 且 `variant=="gaps-on"` 且
`dispatch_mode=="direct"` 时，**打印醒目警告**（不 raise，避免破坏他人现有用法）：

> `--dispatch direct` 装配不含 Agent 工具，缺口注入不会生效；本次结果不能用于缺口编排对照。

并在 `run_payload` 里记 `"dispatch_mode"` 与 `"gap_injection_effective": bool`
（= dispatch_mode == "main" 且 variant == "gaps-on"），供报告自证。

**验收**：单测覆盖四种组合；报告里能看到该字段。

---

### T0.7 跑三级基线（**已定：要跑；执行时点见下方**）

**已定决策**：L3 会跑，范围只 `code` 域。但**不在提案确认时立刻跑**——
执行时点 = T0.1–T0.6 全部完成、且 L1/L2 的单价（每例 token / 耗时）已经测出来之后。
届时跑之前我会再确认一次（外部成本动作）。

先定范围与规模，命令如下：

| 级 | 命令（示意） | 目的 | 预计 |
|---|---|---|---|
| L1 | `--mode live --dispatch main --domain code --max-cases 1` | 链路是否通、指标是否非零 | 1 例 |
| L2 | `--domain code --max-cases 3 --repeat 2` | 估单价：每例 model_calls / token / 耗时 | 6 次单例 |
| L3 | `--domain code --variant gaps-on` 与 `gaps-off`，各 `--repeat 2` | 基线入库（阶段 5 的 Baseline 臂） | 7 例 × 2 臂 × 2 轮 = 28 次单例 |

单例上限 180s，L3 粗略估计 1–2 小时机时。**跑之前我会再问一次**，不擅自跑。

**算式里的三个乘数分别是什么**

- **单例**：一道题跑一次，即一次完整 Agent 会话（主 Agent 多轮推理 + 派子代理 + 子代理执行），
  单次可能几十次模型调用，上限由 `--timeout-per-case` 控制。
- **臂**：一组对照配置。现在两个——`gaps-on`（缺口注入开）/ `gaps-off`（关）。
  必须两臂的原因是：要改的就是缺口机制，**只有关掉它才知道它本来有多大作用**，这就是后续对照的参照点。
- **轮**：同一臂重复跑几遍（`--repeat 2`），用来量化模型随机性带来的波动。

`7 例 × 2 臂 × 2 轮 = 28 次单例`。若单例 60 秒 ≈ 28 分钟，若打满 180 秒 ≈ 84 分钟。
所以先跑 L1/L2 量单价，再决定 L3 规模。


---

### T0.8 基线冻结

**做什么**

1. 记录 `commit hash` + 依赖版本 + `run_id` + 关键数字（成功率、委派数、token、终止原因分布）；
2. 写明**本环境测不出来的项**（例如若 provider 不返回 cache 字段，则"cache 命中率：不可得"，
   而不是 0）；
3. 把这份记录放进总纲 §6 的度量章节，作为阶段 1 的回归基准。

**验收**：同一配置连跑两次，比率一致；记录可被后来者按命令复现。

---

## 4. 产出物

| 类型 | 路径 | 说明 |
|---|---|---|
| 代码 | `cloudagent_ext/diagnosis/evaluation/cost.py`（新） | usage 归一化与聚合 |
| 代码 | `cloudagent_ext/diagnosis/evaluation/executors.py` | meta 增加 `usage` / `decision_counts` / `decision_log` / `gap_events` |
| 代码 | `cloudagent_ext/diagnosis/runtime_session.py` | `decision_log` / `gap_events` 采集口（不改判定逻辑） |
| 代码 | `cloudagent_ext/diagnosis/evaluation/runner.py` | token 求和、repeat 聚合修正、dispatch 自检、payload 字段 |
| 测试 | `tests/diagnosis/test_eval_metrics.py`（新） | usage 归一化、repeat 聚合、自检字段 |
| 文档 | `requirements-eval.txt` 或 `docs/` 一节 | 环境固化 |
| 数据 | `eval/baseline/`（或指定目录） | 基线 run 产物 + 人读摘要 |
| 文档 | 总纲 §6 增补 | 基线数字与"不可得项"声明 |

## 5. 依赖关系

**本阶段内部**：T0.1 → T0.2/T0.3/T0.4/T0.5/T0.6（可并行）→ T0.7（依赖前五项合并）→ T0.8。

**被谁依赖**：

| 后续阶段 | 依赖本阶段的什么 |
|---|---|
| 阶段 1（停止判定 + 域维度） | T0.3 的 `decision_counts` 才能算"误停止率"；T0.6 的自检才能证明对照有效 |
| 阶段 2（状态可信） | T0.4 的 `gap_events`（陈旧写入/回退要按事件统计） |
| 阶段 3（上下文） | T0.2 的 token 与 cache（否则无法判断压缩是否伤到命中率） |
| 阶段 5（对照实验） | T0.5 修好的 repeat 聚合 + T0.8 的基线 |

**本阶段不依赖任何后续阶段**——这是它能排第一的前提。

## 6. 需要你决策的三点

| # | 决策点 | 选项 | 决策（2026-10-29） |
|---|---|---|---|
| 1 | 基线覆盖范围 | (a) 只 `code` 域 7 例（无外部依赖）<br>(b) 顺手搭 `cloudagent_sim` 两个 Postgres，把 `sql`/`sync` 也纳进来 | **已定 (a)：先 `code` 域**。先用 7 道零依赖的题验证度量链路成立；`sql`/`sync` 等后续阶段需要多域时再补 |
| 2 | `--repeat` 语义 | (a) 补聚合（median/min/max）<br>(b) 改名 `round1_*` 显式承认只取第一轮 | **已定 (a)：补聚合**。接受可能触发既有测试改动，发生时单独说明 |
| 3 | 是否跑 L3 全量基线 | 是 / 先只跑 L1+L2 看单价再定 | **已定：跑，但不是现在**。执行时点 = T0.1–T0.6 完成且 L1/L2 单价测出之后；**跑之前再确认一次** |


**决策点 1 的展开（各域的题分别需要什么）**

评测是"逐题跑 + 跟标准答案（`ground_truth`）比"。题库按域分五类，共 38 道（`diagnosis/cases/`）：
`sql 14 / code 7 / log 6 / cross 6 / sync 5`。三个域的真实题目长这样：

| 域 | 题目 | 要答对，Agent 必须能访问 |
|---|---|---|
| `code-001` | "InvestigationSession / SessionBudget 是否在主 Agent 的派发链路上生效？请给出证据。" | **本仓代码**（当前目录）——零外部依赖 |
| `sql-001` | "订单列表页按租户查询明显变慢，请诊断原因。" 答案：`orders.tenant_id` 没索引 → 全表扫描 | **一个装了测试数据的 Postgres**（要能跑 EXPLAIN 看到 `Seq Scan`） |
| `sync-001` | "客户反馈订单在报表里查不到，判断有没有同步到下游库，并定位断点。" | **两个库**（上游 `cloudagent_sim` + 下游 `cloudagent_sim_downstream`）做对照 |

所以这个决策点的真实含义是"**这一轮基线先测哪些域的题**"，不是"测多测少"。

**补充：本机环境实际状态（2026-10-29 只读检查）**

- `~/.cloudagent/db_sim.env` **存在**；本机 **5433 端口 Postgres 正在运行**（5432 关闭）；
- 仓库里有灌数据脚本 `tests/fixtures/sql/sync_seed_{primary,secondary}.sql`（各 43 行）
  与演示脚本 `scripts/demo-sync.ps1`（该脚本自注"依赖本机环境，CI 不可复现"）；
- `logs-sim/` 目录**不存在**（`log` / `sync` 域可能用到）。

→ 因此"选 (b)"的成本比初稿估计的低（不是从零搭库），但仍建议先 (a)：
**先用 7 道零依赖的题验证"度量链路"本身成立**（token 能采到、终止原因能记、repeat 聚合对），
再扩范围。另外 `sim` 库里是否已有数据尚未验证，选 (b) 时需先查。


## 7. 风险与应对

| 风险 | 表现 | 应对 |
|---|---|---|
| token 键名不统一 | 某 provider 返回 `prompt_tokens`，代码只认 `input_tokens` → 静默 0 | 归一化 + `calls_without_usage` 计数，报告显式标"不可得" |
| cache 字段可能根本不存在 | DeepSeek/ModelScope 未必返回 cache 命中信息 | 指标允许为空；**绝不把"没有字段"写成"命中率 0"** |
| repeat 修正改变历史可比性 | 之前跑的报告数字含义变了 | 在报告与文档里注明口径变更时间点 |
| 修 repeat 触发既有测试 | `test_evaluation_runner.py` 断言旧字段 | 已接受（决策点 2 选 A）；改动单独说明理由与影响面 |
| live 成本与时长 | L3 可能 1–2 小时、token 不可预估 | 三级递进；L3 前再看一次单价 |
| 单例超时被记为 crash | 180s 上限可能不够（主 Agent 模式回合多） | 先 L1 观察实际耗时，再定 `--timeout-per-case` |
| 只覆盖 `code` 域 | 得出的基线不代表 sql/log | 明确声明覆盖范围；多域等阶段 1 |
| 埋点引入回归 | 采集代码碰了 `_agent_call` / `harvest_gaps` | 埋点只追加、不改控制流；每步跑定向测试，收尾跑全量 |

## 8. 工作量与执行顺序建议

| 步 | 规模 | 是否要 live | 备注 |
|---|---|---|---|
| T0.1 | 小 | 否 | 半小时级 |
| T0.2 | 中 | 否（单测）+ 是（验证一次） | 最需要小心的是键名归一 |
| T0.3 | 中 | 否 | 只加采集，不改判定 |
| T0.4 | 小 | 否 | 只记已有迁移 |
| T0.5 | 小 | 否 | 已定按方案 A 补聚合，可能改既有测试 |
| T0.6 | 小 | 否 | 纯提示 + 一个 payload 字段 |
| T0.7 | — | **是** | 已定要跑（只 code 域），时点见 §6 决策点 3；跑前再确认 |
| T0.8 | 小 | 否 | 文档 |

建议执行顺序：T0.1 → T0.6 → T0.3 → T0.4 → T0.2 → T0.5 → （确认后）T0.7 → T0.8。
把 T0.6 提前是因为它能防止后面所有 live 跑白费。

---

## 9. 决策记录

| 时间 | 决策 | 影响 |
|---|---|---|
| 2026-10-29 | 基线只覆盖 `code` 域 7 例（决策点 1 = a） | T0.7 的 L3 只跑 code；`sql`/`sync` 延期到后续阶段 |
| 2026-10-29 | `--repeat` 采用补聚合方案（决策点 2 = a） | T0.5 改 `_experiment_stats`，可能触发既有测试改动 |
| 2026-10-29 | L3 要跑，但不在提案确认时立即跑（决策点 3） | 时点 = T0.1–T0.6 完成 + L1/L2 单价已测出；**跑前再确认一次** |

---

## 10. 执行记录

### 10.1 已完成（T0.1 – T0.6，2026-10-30）

| 步 | 交付 | 位置 |
|---|---|---|
| T0.1 | 独立的依赖清单，区分「测试必需」与「live 必需」，注明 `PYTHONPATH='.;extensions/lkb/src'` 的来历 | `requirements-eval.txt` |
| T0.6 | `gap_injection_effective` 字段（= `dispatch_mode=="main" and variant=="gaps-on"`）；live + gaps-on + direct 时向 stderr 打醒目警告（不 raise，`direct` 仍是合法用法） | `runner.py` |
| T0.3 | `decision_log` / `decision_seq` / `decision_counts`；在 `runtime.decide()` 内记录（唯一入口，含主流程） | `runtime_session.py` |
| T0.4 | `gap_events` / `gap_event_seq`；四种迁移 `new` / `blocked` / `resolved` / `restated` 全部记录 | `runtime_session.py` |
| T0.2 | `summarize_usage()` / `sum_usage_summaries()`：OpenAI / Anthropic / 嵌套 `details.cached_tokens` 三种键名归一；认不出记 `calls_without_usage`，`available=False` 显式标"不可得" | `evaluation/cost.py`（新） |
| T0.5 | `_SCALAR_KEYS` 也做跨轮 median/min/max + `_series`；泄漏守卫改用 `injected_dispatches_max` | `runner.py` |
| 测试 | `tests/diagnosis/test_eval_metrics.py`（21 个用例） | — |

### 10.2 三处与提案不一致的地方（执行时才发现）

**① T0.5 没有触发既有测试改动。** 提案预测「可能需改 `test_evaluation_runner.py`」，
实际 `test_evaluation_runner.py` + `test_ab_experiment.py` 33 passed 全绿。
原因：这些测试没有断言 `experiment` 里那几个标量的具体数值，只断言比率。**预判偏保守，实际更顺利。**

**② 逐 case 明细不在 `run.json` 里。** `write_report()` 把每个 case 单独写到
`<run_dir>/cases/<case_id>.json`，`run.json` 只放汇总。测试按实际结构写。

**③ 离线执行器也要补同样四个键。** `OfflineExecutor.run_case` 自己造 meta
（原本只有 `{"fixture": ...}`），不含 live 那套采集字段。为了让报告侧不必按 mode 分支，
给它补了 `decision_counts` / `decision_log` / `gap_events` / `usage` 的中性值
（**不是"测出来是 0"，是"离线模式不采集"**）。

### 10.3 语义变更（读旧报告时要注意）

`experiment` 里 `delegations` / `gaps_total` / `gaps_resolved` / `injected_dispatches` /
`cases_with_injection` / `main_tool_calls` / `sub_tool_calls` 这几个标量，
**语义从"第一轮的值"改成了"跨轮中位数"**。字段名没变（下游 `int(...)` 仍可用），
但 `--repeat > 1` 时数值会与旧报告不同。同时新增了 `<key>_min` / `<key>_max` / `<key>_series`。

### 10.4 验证结果

```
tests/diagnosis/test_eval_metrics.py           23 passed     ← 新增
tests/diagnosis/test_evaluation_runner.py
  + test_ab_experiment.py                      33 passed     ← 零改动
tests/diagnosis/（全量）                620 passed, 25 skipped   （改造前 597）
```

离线 CLI 冒烟（`--mode offline --domain sync`，不调模型）落盘核对：

```
gap_injection_effective: False        ← direct 模式，自检生效
delegations median/series/max: 0 [0.0] 0
usage_available: False  cache_field: ''    ← 离线不采集，如实标"不可得"
meta keys: decision_counts / decision_log / gap_events / usage ✓
```

### 10.5 未做（等确认）

- **T0.7 跑三级基线**：未执行。需要先确认 L1/L2 的机时单价，且跑 live 要再确认一次。
- **T0.8 基线冻结**：依赖 T0.7。

---

## 11. 审查记录（2026-10-30，实现后自查）

会写完不算完，隔一遍 diff 又发现三处真问题，都已修并补了用例：

| # | 问题 | 症状 | 修法 |
|---|---|---|---|
| 1 | `gap_injection_effective` 少了 `mode == "live"` 条件 | offline 回放 + `--dispatch main` 会把它标成 `True`——明明没跑模型，却声称"注入生效"。**而且我最初的测试把这个错误行为当成了期望值** | 抽成 `_gap_injection_effective(mode, dispatch_mode, variant)` 纯函数，三条件缺一不可；测试改成对四组组合逐一断言 |
| 2 | `decision_counts` 从 `decision_log` 反推 | `decision_log` 有 50 条上限，判定超过 50 次后早期记录被截掉 → **计数漏算**。实测 8 次判定只数出 5 次 | 新增 `decision_tallies` 累加器，与日志截断解耦；补用例 `test_counts_survive_log_truncation` |
| 3 | `_median_of([min(values)])` | 用"取一个元素的中位数"来求最小值，能跑但读起来像错的 | 直接 `min(values)` / `max(values)` |

另外两处文档不同步（也是这次审查发现的）：

- `requirements-eval.txt` 里的用法示例还写着改名前的 `requirements-test.txt`；
- `diagnosis-orchestration-refactor.md` 的"未完成"表还写着「P0 未开始」「A2 阻塞在决策」。

**教训**：埋点类代码的 bug 不报错、也不改变主流程行为，只会让数字静默变少/变错。
所以这类改动的验收必须是**形状 + 数值双重断言**（键存在 ≠ 数值对），
用例里要有一条"截断后计数仍然对"这种专门打脸的场景。

### 11.1 追加：报告落盘崩溃（2026-11-01 首次 live 暴露）

第一次真跑 live 时，报告在写 `cases/<id>.json` 处崩掉：

```
json.decoder.JSONDecodeError: Invalid \escape: line 1 column 194463
```

根因不在这次改造，而在既有的脱敏写法：`report.py` 把**脱敏正则在
`json.dumps` 之后的 JSON 文本**上跑（`json.loads(redact_sensitive(json.dumps(case)))`），
一旦正则匹配跨过 `\\` 边界，就会留下 `\U` 这种非法转义 —— 而这台机器上到处都是
`C:\Users\...` 路径，所以**几乎必然触发**。
后果是：整轮数据只落下了 `run.json`，逐 case 明细与 trace 全丢。

修法：新增 `redact_payload()`，**结构化脱敏**（逐字符串值脱敏），顺序改为
`_normalize(payload)` → `redact_payload(...)` → `_dump(...)`。JSON 语法只由
`json.dumps` 最后负责一次，从根上没有这类问题。
`redact_sensitive` 仍用于纯文本（trace 的 markdown 回放）。

用例：`tests/diagnosis/test_report_redaction.py`（8 个，含"路径 + 密码同段"的组合）。



