# EVAL-P1a 设计补充：RunRecord v1 字段定义

> 配套任务卡：[`../tasks/eval-p1a-runrecord.md`](../tasks/eval-p1a-runrecord.md)
> 总设计：[`eval-system-design.md`](eval-system-design.md) §3
> 本文件把 §3 的 schema **细化到可直接实现的程度**——字段名、类型、必填性、为空的语义。

---

## 1. 两个类型的分工

| 类型 | 方向 | 含答案？ | 谁写 |
|---|---|---|---|
| `RunRequest` | 评测仓 → 产品 | ❌ **绝不** | 评测仓 |
| `RunRecord` | 产品 → 评测仓 | ❌ 也不含 | 产品 |

**两者都不含 ground_truth。** 答案是评测仓的私有资产，只在评分阶段用。

---

## 2. `RunRequest` v1

```python
@dataclass(frozen=True)
class RunRequest:
    schema_version: int = 1
    request_id: str = ""
    case_id: str = ""
    domain: str = ""
    question: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `schema_version` | int | ✅ | 必须 == 1（本版本） |
| `request_id` | str | ✅ | 非空；由评测仓生成，用于关联 |
| `case_id` | str | ✅ | 非空；产品**只把它当标识**，不去查题库 |
| `domain` | str | ✅ | `sql` / `code` / `log` / `cross` / `sync` |
| `question` | str | ✅ | 非空；**产品唯一的任务输入** |
| `context` | dict | ❌ | 题面附加上下文（sql 语句 / trace_id / 时间窗等） |
| `options` | dict | ❌ | 见 §2.1 |

### 2.1 `options` 的键（全部可选，缺省用产品默认）

| 键 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `dispatch_mode` | `direct` / `main` | `main` | `main` = 走主 Agent 派发（能触发缺口机制）；`direct` = 直驱子代理 |
| `grade_source` | `auto` / `main` / `subagent` | `auto` | 只影响**评测仓评分时选哪段文本**，产品只需如实记录两段 |
| `timeout_sec` | float | 300 | 单 case 超时 |
| `permission_mode` | `dontAsk` | `dontAsk` | **本版本只允许 `dontAsk`**，传其它值报错 |

> `permission_mode` 白名单只有一个值，是有意的：现在把口子留着，
> 将来放宽时能看见 diff。**不写"允许任意值"**。

### 2.2 严格校验规则

```python
def request_from_json(payload: dict) -> RunRequest:
    # 1. schema_version 必须是 1
    # 2. 未知字段（不在上面 7 个里）→ RunRequestError
    #    特别是 ground_truth / root_causes / expected_agents / match_terms
    # 3. domain 必须在白名单
    # 4. request_id / case_id / question 非空（strip 后）
    # 5. options.permission_mode 必须是 dontAsk
```

**未知字段报错的理由**（再强调一次，这是本卡的安全价值）：
静默忽略会让"把整份 case 传进来"发生得无声无息，症状是"分数莫名其妙特别高"。

---

## 3. `RunRecord` v1

### 3.1 顶层结构

```jsonc
{
  "schema_version": 1,
  "record_id": "rec-sql-001-20261107T113000",
  "request_id": "req-0001",
  "case": { "case_id": "sql-001", "domain": "sql" },
  "run": { "started_at": "...", "finished_at": "...", "elapsed_sec": 123.4 },
  "subject": { ... },
  "outcome": { ... },
  "trace": { ... },
  "mechanism": { ... },
  "usage": { ... }
}
```

### 3.2 `subject`（被测系统身份，R7 全链路版本化要求）

```jsonc
{
  "product": "cloudagent",
  "version": "1.2.1",
  "git_sha": "ab12cd3",          // 取不到写 "unknown"，不许编
  "model": "deepseek-v4.1-flash",
  "provider": "deepseek",
  "dispatch_mode": "main",
  "grade_source": "auto",         // 请求时声明的值
  "permission_mode": "dontAsk",
  "arm_env": { "CLOUDAGENT_GAP_INJECTION": "on" }   // 本次运行相关开关快照
}
```

| 字段 | 必填 | 取不到时 |
|---|---|---|
| `product` / `version` | ✅ | — |
| `git_sha` | ✅ | `"unknown"`（**不许猜**） |
| `model` / `provider` | ✅ | `"unknown"` |
| `dispatch_mode` | ✅ | — |
| `arm_env` | ❌ | `{}` |

> `arm_env` 只记录**会影响行为的机制开关**（`switches.SWITCHES` 里的 5 个），
> 不要 dump 整个 `os.environ`——那会把凭据写进记录。

### 3.3 `outcome`

```jsonc
{
  "status": "ok",                 // ok|timeout|crashed|unfinished|invalid_output
  "error": null,                  // status != ok 时的原因（已脱敏）
  "raw_output": "...",            // 评分对象文本（子代理协议 JSON 或主代理散文）
  "main_answer": "...",           // main 模式下主 Agent 原文，评分不用但保留
  "graded_text": "..."            // 实际参与评分的文本；由 grade_source 决定
}
```

**五档定义**（必须与现有 `evaluation/scoring.categorize()` 语义一致，不要另立标准）：

| status | 含义 |
|---|---|
| `ok` | 正常跑完且有输出 |
| `timeout` | 超时 |
| `crashed` | 执行层异常（含"服务端返回 500 / 连接断开"这类硬异常） |
| `unfinished` | **空输出** / 撞轮次上限 / 明显截断（沿用 `_UNFINISHED_SENTINELS` 判定） |
| `invalid_output` | 有输出但不合协议 |

> **⚠️ 修订记录（2026-11-07，P1a 审查中更正）**
>
> 本文初版曾列出**六档**并单列 `empty`（"跑完但输出为空"）。
> **那是错的**，已移除。理由：现有 `scoring.categorize()` 把空输出归 `unfinished`，
> 且 `_looks_unfinished()` 的 docstring 已论证过这个分类——
> **空输出意味着"模型没拿到作答机会"，属链路问题，不是格式问题**。
> 保留 `empty` 会造成 P3 有两条互斥判定路径。
>
> 教训：判定表应当**先从现有实现反推**，而不是凭"执行层事实"想当然地写。
> 本次由 ZCode 在 handoff 的"规格疑问 2"中指出。

### 3.4 `trace`（optional）

```jsonc
{
  "events": [ ... ],        // 主循环事件（tool_use / tool_result）
  "calls": [ ... ],         // 每次模型调用摘要
  "tool_events": [ ... ]    // CLI 层聚合
}
```

**可以是 `null` 或缺失**。黑盒 subject 不提供 trace 也合法；
评分器必须能在无 trace 时降级（并在报告里标"该指标不可用"）。

`calls` 的每一项沿用现有 `_RecordingProvider` 的形状：
`{n, elapsed_sec, model, usage, finish_reason, tool_uses, content}`。
**注意 `content` 可能很大**——记录时应截断到合理长度（建议 20000 字符，与
`_EVENT_TEXT_LIMIT` 一致），并在截断时加 `"truncated": true` 标记。

### 3.5 `mechanism`（optional，但**强烈建议**提供）

```jsonc
{
  "delegations": 3,
  "agents_dispatched": ["sql-diagnosis"],
  "gaps_total": 12, "gaps_resolved": 5, "injected_dispatches": 1,
  "decision_counts": {...}, "decision_log": [...],
  "gap_events": [...],
  "compaction": {...}, "recall_count": 0, "recall_miss": 0
}
```

这些是**机制遥测**，也是这个项目 4 个阶段工作的价值所在。
缺了它们，评测就退化成"只看最终答案对不对"，看不出机制起没起作用。

### 3.6 `usage`

```jsonc
{
  "input_tokens": 1167134,
  "output_tokens": 30708,
  "cached_input_tokens": 0,
  "model_calls": 45,
  "calls_without_usage": 0,
  "available": true
}
```

**`available=false` 时**：`input_tokens` / `output_tokens` / `cached_input_tokens` 一律为 `null`，
**不是 0**。`calls_without_usage` 仍要填（它说明"有多少次调用没采到"）。

> 这条继承 `evaluation/cost.py` 已确立的纪律。现有 run.json 里已经受过教训：
> 报告看不出"某臂省了 token"是真省了还是没采到。

---

## 4. `CaseRun → RunRecord` 的字段映射表

`execute.py` 的核心就是这张表。**这是实现时唯一需要对照的东西**：

| `CaseRun` 字段 | → `RunRecord` | 转换规则 |
|---|---|---|
| `case_id` | `case.case_id` | 直接 |
| （请求里） | `case.domain` | 从 `RunRequest.domain` |
| `raw_output` | `outcome.raw_output` | 直接 |
| `main_answer` | `outcome.main_answer` | 直接 |
| `error` | `outcome.error` | `redact_sensitive()` 脱敏 |
| `error` 是否为空 | `outcome.status` | 见下方判定表 |
| `events` | `trace.events` | 直接（必要时截断） |
| `calls` | `trace.calls` | `content` 截断 + `truncated` 标记 |
| `meta.*` | `mechanism.*` | 逐键搬运（见下） |
| `meta["usage"]` | `usage` | 已经是 `summarize_usage()` 的形状，直接搬 |

### 4.1 `status` 判定顺序（必须按此顺序）

```
1. error 非空 且 含 "timeout"  →  timeout
2. error 非空                  →  crashed
3. raw_output.strip() == ""    →  unfinished      ← 空输出归 unfinished（不是 empty）
4. 命中 _UNFINISHED_SENTINELS  →  unfinished
5. 有输出但不合诊断协议        →  invalid_output
6. 其它                        →  ok
```

**注意**：第 4、5 步的判定逻辑**本卡不实现**——那是评分层的事（P3）。
本卡只需要：
- 能确定 `ok` / `timeout` / `crashed` / `unfinished`（空输出这一档）四类
- 对"撞顶 / 不合协议"**暂时记为 `ok` 并在记录里加
  `"status_provisional": true`**，等 P3 的评分器来细分

> 为什么要这样：如果在 P1a 就把协议解析塞进来，等于把评分逻辑混进执行层，
> 违反红线 1。而 `status_provisional` 标记让 P3 知道"这条还没细分过"。
>
> **第 3 步为何归 `unfinished` 而非 `empty`**：见 §3.3 的修订记录。
> 空输出 = 模型没拿到作答机会 = 链路问题，与"答完了但格式不对"是两回事。

### 4.2 `mechanism` 的搬运白名单（只搬这些，别的不要）

```
delegations / agents_dispatched / gaps_total / gaps_resolved / injected_dispatches
decision_counts / decision_log / gap_events
compaction / recall_count / recall_miss
state_revision / stale_discarded / assessments
```

**白名单而非黑名单**：`meta` 里可能有将来新增的调试字段，全搬会让 RunRecord 无限膨胀，
也会让"契约稳定"变成空话。新增要改 schema 版本。

---

## 5. 一个容易做错的地方：`graded_text`

`outcome` 里有三段文本，容易混：

| 字段 | 是什么 | 谁用 |
|---|---|---|
| `raw_output` | 子代理协议 JSON（`main` 模式下从会话账本取） | **评分用** |
| `main_answer` | 主 Agent 的散文回复 | 人读 / 回放 |
| `graded_text` | 按 `grade_source` 选出来的那一段 | 评测仓评分时直接用，免得再选一次 |

**为什么要有 `graded_text`**：选哪段评分的逻辑（`grade_source`）现在在产品仓
`executors.py` 的 `_wants_subagent_grade()` 里。如果评测仓还要重算一次，两边规则会漂。

现有实现（**照抄这个语义，不要另立**）：

```python
def _wants_subagent_grade(dispatch_mode: str, grade_source: str) -> bool:
    if grade_source == "subagent":
        return True
    if grade_source == "main":
        return False
    return dispatch_mode == "main"     # auto: main→子代理结果, direct→主输出
```

→ **产品算出 `graded_text` 并记录**，评测仓直接用。这样"选谁评分"只有一处实现。

取不到被评对象时（如 `main` 模式但没派发子代理），`graded_text` 写空串，
`outcome.status` 应为 **`unfinished`**（"没拿到作答机会"，同 §3.3 的判定口径）。

> 这条在 P1a 审查时更正过：初版写的 `empty` 已废弃。实现方（ZCode）按当时写下的
> `empty` 落地，审查时被它的"规格疑问 2"发现并纠正——**这是我文档的错**。

---

## 6. 实现顺序建议

1. `record.py`（纯 schema + 校验 + 往返测试）——**先做这个，它是地基**
2. `test_record.py` 跑通
3. `execute.py`（先只做 `CaseRun → RunRecord` 的转换，用 fake CaseRun 测）
4. `test_execute.py` 跑通
5. `cli.py` + 注册子命令
6. `test_cli.py` 跑通
7. 全量回归 + ruff + 反向依赖扫描
8. （可选）真跑 1 个 case

**第 3 步之前不要碰真实执行**——先把"契约本身对不对"验完，
再让它去接真实数据。反过来的话，契约和实现会一起错，分不清谁的问题。

---

## 7. 与 P2 的接口约定

P1a 交付后，P2 会拿这批 RunRecord 做等价性验证。所以 P1a 必须保证：

1. **同一 case 两次运行，除 `run`/`record_id` 外字段结构完全一致**（便于 diff）
2. **`record_to_json` 的字段顺序稳定**（两次序列化逐字节相等）
3. 历史 run 迁移时（P2），能映射的字段必须与 P1a 的字段**同名同义**

第 3 条现在就要留意：`eval/runs/*/cases/*.json` 里的字段名可能与 P1a 不同。
**实现时不要为了迁就历史而改名**——历史迁移由 P2 写适配器，P1a 保持 schema 纯净。
