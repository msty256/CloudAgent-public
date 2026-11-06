# CloudAgent 评测体系设计（v1）

> 日期：2026-11-07 · 作者：DSH Lead · 状态：**待评审**
> 前置决策：[`eval-system-discussion.md` §11](./eval-system-discussion.md#11-决策记录2026-11-07项目所有者拍板)
> 已定：能力/质量为评价主轴 · 无真实事故数据 → 生成器为主 · **独立 git 仓库** · 不依赖 Inspect AI

---

## 1. 目标与非目标

### 1.1 要解决的四件事

| # | 现状问题（已量化） | 设计要给出的答案 |
|---|---|---|
| 1 | 评测代码 134 KB 长在产品包里，产品反向 import 评测（`log/tools.py:41`） | **独立仓库** + 单向依赖 + 契约解耦 |
| 2 | 38 题 / 91 KB，统计上无意义（1 题 = 2.6 个百分点） | **故障注入生成器**，目标 300+ 生成题 + 40+ 金标题 |
| 3 | 评分靠词表，已实测 ~1/3 假阴性（33% 实际应为 67%） | **分层评分**：确定性断言优先，词表只做兜底，语义归一化 |
| 4 | 无冻结/holdout/canary/显著性 → 不能当 RSI 适应度 | **治理层**：manifest 冻结、holdout 隔离、canary、CI 区间 |

### 1.2 非目标（明确不做，避免范围蔓延）

| 不做 | 理由 |
|---|---|
| 通用评测框架 | 只服务 CloudAgent；通用化会稀释掉最有价值的部分（证据协议评分） |
| 评全仓能力（CLI/TUI/skills/provider） | 已定 Q1：只评 diagnosis。其他机制用**产品仓自己的单测**守，不进评测体系 |
| 把成本/延迟做成主指标 | 已定 Q1：只作诊断信息记录。RSI 约束里再作为门限 |
| 真实事故 replay 数据集 | 已定 Q3：无数据源。**只预留格式**，不实现 loader |
| Docker/K8s 沙箱 | 本机无 Docker/WSL（已实测）。用「进程内隔离 + 临时库 + 临时目录」替代 |
| 引入 Inspect AI 运行时 | 已定 D3。借用抽象，不引依赖 |

---

## 2. 架构总览

### 2.1 两个仓库，一个契约

```
┌───────────────────────────────────────────────────────────────┐
│  CloudAgent（产品仓，被测系统）                                  │
│                                                               │
│  cloudagent_ext/diagnosis/eval_support/    ← 新增，~35 KB       │
│    ├── record.py       RunRecord v1 的 schema + 序列化          │
│    ├── execute.py      跑一个 case 并产出 RunRecord             │
│    └── cli.py          `cloudagent eval-run` 子命令             │
│                                                               │
│  cloudagent_ext/utils/redaction.py        ← 新增，从 report.py 迁 │
│                                                               │
│  ❌ 删除：diagnosis/evaluation/（134 KB）                        │
│  ❌ 删除：diagnosis/cases/（91 KB）                              │
│  ❌ 删除：diagnosis/case_library.py                              │
└──────────────────────────┬────────────────────────────────────┘
                           │  只通过 RunRecord 文件交换
                           │  产品 **只收到 question，永远收不到 ground_truth**
┌──────────────────────────▼────────────────────────────────────┐
│  cloudagent-eval（独立 git 仓库，新）                            │
│                                                               │
│  cloudagent_eval/                                             │
│    ├── dataset/     加载、校验、manifest、split、冻结           │
│    ├── runner/      驱动产品 CLI，收集 RunRecord                │
│    ├── scorers/     分层评分器（每层可独立版本化）               │
│    ├── metrics/     统计聚合（Wilson CI / bootstrap / pass^k）  │
│    ├── report/      machine JSON + human markdown + 趋势       │
│    ├── governance/  canary、污染检测、变更告警                  │
│    └── adapters/    subject 适配器（cloudagent-cli / inspect 预留）│
│                                                               │
│  datasets/   golden/（手写金标） generated/（生成器产物）        │
│  environments/  sql/ log/ code/（环境定义，评测仓拥有）          │
│  generators/    sql/ log/ code/（故障注入）                     │
│  runs/        产物（gitignore）                                │
└───────────────────────────────────────────────────────────────┘
```

### 2.2 为什么"产品只收到 question"是硬约束

这是本设计的**安全性基石**，不是风格偏好：

- 评测仓读 case 文件 → 取出 `input.question` + `input.context` → 写成 `RunRequest`
- 产品收到 `RunRequest`，**结构上没有 ground_truth 字段**
- 因此"被测系统看到答案"这类污染**在协议层就不可能出现**

对比现状：`cases/*.json` 整份放在产品包里，`runner.py` 同时持有题面与答案。
虽然当前代码没有喂给模型，但**没有任何机制阻止将来有人这么做**。

> 这条同时满足讨论稿 R8（不可被优化器直接读写）；对 RSI 尤其关键——
> 一旦优化循环能改到答案，整个评测立刻失效。

---

## 3. 核心契约：RunRecord v1

### 3.1 RunRequest（评测 → 产品）

```json
{
  "schema_version": 1,
  "request_id": "req-0001",
  "case_id": "sql-001",
  "domain": "sql",
  "question": "订单列表页按租户（tenant_id）查询明显变慢（约 1 秒），请诊断原因并给出建议。",
  "context": { "sql": "SELECT * FROM orders WHERE tenant_id = 7", "table": "orders", "symptom": "slow" },
  "options": {
    "dispatch_mode": "main",
    "grade_source": "auto",
    "timeout_sec": 300,
    "permission_mode": "dontAsk"
  }
}
```

**注意**：没有 `ground_truth`、没有 `expected_agents`、没有 `safety_expectations`。
这些全是评测侧私有信息。

### 3.2 RunRecord（产品 → 评测）

```json
{
  "schema_version": 1,
  "record_id": "rec-...",
  "run": { "started_at": "...", "finished_at": "...", "elapsed_sec": 123.4 },

  "subject": {
    "product": "cloudagent", "version": "1.2.1", "git_sha": "abc1234",
    "model": "deepseek-v4.1-flash", "provider": "deepseek",
    "dispatch_mode": "main", "grade_source": "subagent",
    "arm_env": { "CLOUDAGENT_GAP_INJECTION": "on", "...": "..." },
    "permission_mode": "dontAsk"
  },

  "case": { "case_id": "sql-001", "domain": "sql" },

  "outcome": {
    "status": "ok | timeout | crashed | empty | unfinished | invalid_output",
    "error": null,
    "raw_output": "（子代理或主代理的最终文本，原样）",
    "main_answer": "（main 模式下主 Agent 的散文，评分不用但保留）",
    "graded_text": "（实际参与评分的文本）"
  },

  "trace": {
    "events": [ "（主循环事件，含 tool_use / tool_result）" ],
    "calls":  [ "（每次模型调用的摘要：n/elapsed/model/finish_reason/tool_uses/content）" ],
    "tool_events": [ "（CLI 层聚合的工具事件）" ]
  },

  "mechanism": {
    "delegations": 7, "agents_dispatched": ["sql-diagnosis", "..."],
    "gaps_total": 20, "gaps_resolved": 0, "injected_dispatches": 1,
    "decision_counts": {"budget_available": 1}, "decision_log": [ "..." ],
    "gap_events": [ "..." ],
    "compaction_stats": { "..." : "..." }
  },

  "usage": {
    "input_tokens": 1167134, "output_tokens": 30708,
    "cached_input_tokens": 0,
    "model_calls": 45, "calls_without_usage": 0, "available": true
  }
}
```

### 3.3 契约的三条规则

1. **只增不改**：`schema_version` 升级才允许破坏性变更；评测仓必须能读它声明支持的所有版本。
2. **`mechanism` 与 `trace` 是 optional**：黑盒 subject（如将来接别的 agent）可只实现 `outcome`。
   评分器必须能在缺少 `mechanism` 时降级（并在报告里标明"该指标不可用"）。
3. **`usage.available=false` 时不得当 0**：继承现有 `cost.py` 的正确做法——
   采不到就说采不到，绝不把"没有字段"写成"0 token"。

### 3.4 契约带来的三个直接收益

| 收益 | 说明 |
|---|---|
| **执行与评分解耦** | 录一次 RunRecord，可以反复用不同评分器重算——**改评分规则不用重跑模型** |
| **历史可重评** | 现在的 16 次 run 可以转成 RunRecord，用新评分器重算，直接验证"33%→67%" |
| **可离线开发** | 评测仓用录好的 RunRecord 当 fixture 开发评分器，**零模型成本、零环境依赖** |

> 第二条是本次分工的关键：**先证明新评分器在历史数据上等价或更好，再谈新数据**。

---

## 4. 数据层

### 4.1 三个数据来源（对应"无真实事故"的约束）

| 来源 | 规模目标 | GT 可信度 | 用途 |
|---|---|---|---|
| **golden**（手写） | 40–60 题 | 人工确认，最高 | 主指标；**对外只报这个** |
| **generated**（故障注入） | 300–800 题 | 构造 + 实环境验证 | 覆盖率、鲁棒性、RSI 内循环 |
| **holdout**（隔离） | golden 的 20–30% | 同 golden | 防过拟合；**不进仓库** |

**报告纪律**：golden 与 generated **分开报**，不合并成一个"准确率"。
合并会制造一种虚假的精确感——生成题的难度分布与真实题不同。

### 4.2 故障注入生成器（主力）

#### 通用模式：`Scenario = Environment × Fault × Question`

```
Environment  环境的确定性构造（DB 数据/索引、日志序列、代码样本项目）
Fault        注入的缺陷（本次要诊断的那个根因）
Question     由 Environment + Fault 推导出的题面
GroundTruth  由 Fault 推导 + **在真实环境上验证**
```

**关键：GT 不是"断言出来的"，是"构造出来再验证的"**：

```
1. 生成 Environment（建库/建日志/建项目）
2. 注入 Fault
3. 用产品自己的只读工具（explain_sql / get_indexes / search_logs / find_symbol）
   在环境上实跑，把观测结果写进 GT 的 verification 字段
4. 断言"观测结果确实支持这条 GT"——不成立就丢弃该 case，不入库
```

这一步把 P1 手工做的"11 题逐条真库验证"变成了**流水线**。

#### 分域设计

**SQL 域**（先做，最容易验证）

| 维度 | 取值 |
|---|---|
| 表规模 | 1k / 10k / 50k / 500k 行 |
| 索引集 | 无二级索引 / 单列索引 / 复合索引 / 表达式索引 / 覆盖索引 |
| 查询形态 | 等值过滤 / 范围 / 表达式包裹 / JOIN / ORDER BY / 深分页 / 聚合 |
| 数据分布 | 均匀 / 倾斜 / 高基数 / 低选择性 |
| 故障 | 缺索引 / 索引不可用（表达式/类型转换）/ 选择性误判 / 统计陈旧 |

GT 由"实跑 EXPLAIN + pg_indexes"得出 → 与现有 11 题同源。

**日志域**

| 维度 | 取值 |
|---|---|
| 事件链 | 完整 trace / 部分 trace / trace 缺失 |
| 首异常位置 | 上游 / 中游 / 下游 / 多个候选 |
| 噪声 | 干扰异常 / 时序错位 / 跨小时边界 |
| 故障 | NPE / 超时 / 熔断 / 配置缺失 / 数据不一致 |

**代码域**

用 `docs/prompts/java-sample-project.md` 生成样本项目，注入已知缺陷。
GT = 缺陷所在符号 + 调用链 + 为什么是根因。

**cross 域**（最难，最后做）

跨域需要"同一根因在日志和代码都能看到"。生成器要保证**两条证据链指向同一 Fault**。

#### 同质化风险与对策

生成题最大的敌人是"模型见过一种就全会"。对策：

1. **结构性差异而非数值差异**：换表规模是数值差异（模型无感），换"索引为何不可用"才是结构差异。
2. **多样性度量**：报告里给出"已覆盖的根因类型数"，不只报题数。
3. **生成集与金标分开报**：生成集分数高不代表真实能力。
4. **定期人工抽检生成题**：抽 5%，人判断"这题是否合理、GT 是否正确"。

### 4.3 数据集格式与 manifest

```
datasets/golden/
  manifest.json          # 版本、总哈希、每题的声明变更
  sql/sql-001.json       # 题目（含 ground_truth，评测侧私有）
  ...
```

```json
{
  "dataset_id": "golden-v1",
  "created_at": "2026-11-07",
  "content_hash": "sha256:...",
  "case_count": 46,
  "splits": { "main": [...], "holdout": [...] },
  "changelog": [
    {"date": "2026-11-07", "change": "从产品仓迁入 39 题", "by": "migration"}
  ]
}
```

**冻结规则（R1）**：跑评测时校验文件哈希 == manifest 里的哈希；
不一致且 manifest 无对应 changelog → **报错拒绝运行**（不是警告）。
理由：静默改题会让"分数涨了"变成无法解释的事。

---

## 5. 评分层

### 5.1 分层原则（对 Q1=能力/质量 的落地）

| 层 | 判什么 | 实现方式 | 可信度 |
|---|---|---|---|
| **S0 解析** | 输出能否按协议解析 | 确定性 | 最高 |
| **S1 结论** | 根因对不对 | 确定性断言优先 → 归一化词表兜底 | 高 |
| **S2 证据** | 证据是否支撑结论、是否可核验 | 结构化检查（evidence_id 引用、proves 非空、适用条件） | 高 |
| **S3 行为** | 该不该报、该不该拒 | 结构化（negative / behavior 两类题） | 高 |
| **S4 安全** | 有无越权/泄露/编造 | 正则 + 结构（沿用现有 `safety.py` 逻辑） | 最高 |
| **S5 判断（辅助）** | 结论语义是否正确 | LLM judge，**仅抽样** | 中 |

**S5 默认关闭**。开启时必须同时报"judge 与人工的一致率"；
一致率低于阈值时 judge 分数不进主指标。理由：judge 本身也会错，不能当真理。

### 5.2 修复现有评分口径的三个具体改动

**改动 A：`match_terms` 支持别名组**

```json
"match_terms": ["索引", "tenant_id", "全表扫描|Seq Scan|顺序扫描"]
```

动机：`docs/eval-analysis-2026-11-04.md` 实证 log-006 假阴性
（"无法重建事件链" vs "无法关联"）。修法已在文档里给出，直接采纳。

**改动 B：case 加 `kind` 字段，各归各的分母**

| kind | 含义 | 进哪个分母 |
|---|---|---|
| `root_cause` | 要找根因 | Top-1/Top-3 |
| `negative` | 不该报根因 | 误报率（**不进 Top-1 分母**） |
| `behavior` | 测行为规范（该拒/该要求补充） | 行为通过率 |

动机：现状 log-005（行为题）与 log-003（阴性题）混在 Top-1 分母里，
已实证造成 2/6 的口径污染。

**改动 C：评分器版本化**

`scorer_version` 进 RunRecord 的评分结果。改评分规则必须升版本，
历史结果不自动重算——但提供 `rescore` 命令，一次重算全部历史并出差异报告。

> 这样"改口径导致历史不可比"从**纪律要求**变成**工具能力**。

### 5.3 指标清单（只保留能守住的）

**主指标（对外只报这些）**

| 指标 | 定义 | 防住什么 |
|---|---|---|
| `root_cause_top1` | root_cause 类题中，首选根因命中率 | 只会说套话 |
| `root_cause_top3` | 前三条任一命中 | 漏答 |
| `evidence_sufficient` | 结论所需证据齐备的比例 | 结论对但证据是编的 |
| `evidence_verifiable` | 带可核验关键词的证据占比 | 证据无法复核 |
| `negative_false_positive` | negative 类题的误报率 | 乱报根因 |
| `behavior_pass` | behavior 类题的通过率 | 越权、不要求补充 |
| `safety_violations` | 安全违规计数（必须 0） | 泄露/越权 |

**辅助指标（报告里列出但不进主评分）**

`token_input` / `token_output` / `cache_hit` / `elapsed` / `tool_calls` /
`delegations` / `gaps_total` / `injected_dispatches`

**不做的指标**

- "综合得分"（加权求和）——权重是拍脑袋的，且会掩盖单项退化
- 任何跨数据集合并的平均准确率

---

## 6. 统计层

### 6.1 三个必须有的统计能力

| 能力 | 实现 | 用途 |
|---|---|---|
| **置信区间** | 比例用 Wilson CI；连续值用 bootstrap stderr | 判断"差异是不是噪音" |
| **两臂对比** | 配对比较（同一题集同一题），报差值的 CI | 判断"A 是否真的优于 B" |
| **pass^k** | 同题跑 k 次全对的比例 | 可靠性；RSI 最怕单次运气 |

参数规模建议（基于 116 万 token/例的实测成本）：

| 场景 | 样本 | 重复 | 说明 |
|---|---|---|---|
| L1 smoke | 8–12 题 | 1 | 每次提交；只看"有没有崩"，不报准确率 |
| L2 core | 40 题 golden | 1–2 | 每日；报主指标 + CI |
| L3 full | 全部 golden + 抽样 generated | 3 | 发布前；报 pass^k |
| RSI 内循环 | 生成题抽样 | 1 | 用离线代理指标，见 §8 |

### 6.2 报告纪律（写进报告模板，不靠人记）

- 任何比例必须带 `n` 和 CI；`n < 10` 只描述不推断
- 两臂对比必须报**差值 CI**，不能说"提高了 5 个点"而不给区间
- 生成集与金标**分表**
- 成本必须报"每正确结论的成本"，不是"每 token 的价格"

---

## 7. 治理层（RSI 就绪度）

| 约束 | 落地方式 | 验收 |
|---|---|---|
| **R1 冻结** | manifest 内容哈希；不一致拒绝运行 | 篡改一题 → 运行失败 |
| **R2 holdout** | holdout 题**不放进主仓库**（单独私有位置或加密）；主仓库代码不可读 | 主仓库 grep 不到 holdout 题面 |
| **R3 canary** | 20–30 道"陷阱题"：GT 故意反直觉、或带**唯一标记串**。若模型答出标记串 → 说明它读过题目 | canary 命中数必须为 0 |
| **R4 低方差** | Wilson CI + pass^k；报告"差异是否显著" | 两臂 n=40 时能识别 10 个点以上的差异 |
| **R5 成本门限** | 每个 tier 有 token 预算硬编码，超了中止 | 超预算自动停 |
| **R6 快反馈** | 离线层：RunRecord 重评 + 生成题，秒级 | 改评分器后 1 分钟内出全量重评 |
| **R7 版本化** | `subject.git_sha` + `dataset.content_hash` + `scorer_version` + `harness_version` 四处齐全 | 缺任一项 → 报告标"结论不可引用" |
| **R8 只读** | 产品只收 question（协议层隔离）；评测仓对产品只读 | 设计保证 |

**R6 的实现要点**：RSI 内循环不能跑 live。它跑的是
「录好的 RunRecord + 候选评分器/候选分析器」的**离线重评**，
以及「生成器新题 + 小模型」的**代理评测**。
两者与 live 的相关性要**定期抽样校准**（否则代理指标会漂移）。

---

## 8. 实施计划（分阶段，每阶段可独立验收）

| 阶段 | 内容 | 产出 | 验收标准 | 规模 |
|---|---|---|---|---|
| **P0 还债** | `redact_sensitive` 迁到 `utils/redaction.py`；取消产品→评测反向依赖 | 一行 import 的改变 | 见下方 P0 验收命令，输出为空即通过 | 小 |
| **P1 契约** | 产品侧 `eval_support/`：RunRecord schema + `eval-run` 子命令；**评测仓骨架** | 能对 1 个 case 端到端产出 RunRecord | 手工跑 `cloudagent eval-run --case req.json --out rec.json` 成功 | 中 |
| **P2 等价迁移** | 历史 run → RunRecord；评测仓复刻现有评分器 | **重评差异报告** | 在 16 次历史 run 上，strict 口径与旧评分器**逐题一致** | 中 |
| **P3 修口径** | 别名组 + `kind` 拆分 + 分层评分 | 重评报告：33% → 应在 67% 附近 | 6 个已知样本上达到文档预测值 | 中 |
| **P4 统计** | Wilson CI / bootstrap / pass^k / 两臂对比 | 统计模块 + 报告模板 | 给定同一批记录，CI 与手算一致 | 中 |
| **P5 生成器 PoC** | sql 域生成器（先 1 个域） | 100+ 生成题 + 自动验证流水线 | 抽样 20 题人工判 GT，正确率 ≥ 95% | 大 |
| **P6 治理** | manifest 冻结 / canary / 预算门限 / CI 集成 | 治理模块 + CI job | 篡改检测生效；canary 流程跑通 | 中 |
| **P7 扩域** | log → code → cross 生成器 | 每域 50+ 题 | 同 P5 标准 | 大 |

**里程碑**：P0–P4 完成后，评测体系**已经比现在严格**（可重评、有 CI、口径修好），
且未花一分钱模型成本——这一步应优先交付。

> **任务卡已按本表发布**（2026-11-07）：
> [EVAL-P0](../tasks/eval-p0-redaction.md) · [EVAL-P1a](../tasks/eval-p1a-runrecord.md) ·
> [EVAL-P1b](../tasks/eval-p1b-repo-skeleton.md) · [EVAL-P2](../tasks/eval-p2-migration.md)
> P3–P7 待前四步完成后再出卡（它们的接口依赖 P2 的产出）。

### P0 验收命令（跨平台，不依赖 grep）

```powershell
python - <<'PY'
import glob
hits = [f for f in glob.glob("cloudagent_ext/**/*.py", recursive=True)
        if "__pycache__" not in f
        and "diagnosis/evaluation/" not in f.replace("\\", "/").split("cloudagent_ext/")[-1].replace("\\", "/")
        and "diagnosis.evaluation" in open(f, encoding="utf-8", errors="ignore").read()]
print("残留反向依赖：", hits)   # 期望：[]
PY
```

> 实测基线（2026-11-07）：现在是 `['cloudagent_ext\\diagnosis\\log\\tools.py']` 一条。

**P5 是最大不确定性**：建议先做 sql 单域 PoC，验证"GT 可信 + 题不同质"后再铺开。
若 PoC 失败（生成题质量不达标），回退方案是"手写扩到 100 题 + 承认规模上限"。

---

## 9. 迁移与共存

### 9.1 现有 P1 工作如何处置

P1（sql 11 题 `runtime→static` + `seed.sql` + 静态守门）**不浪费**：

| P1 产物 | 新归属 |
|---|---|
| `tests/fixtures/sql/seed.sql` | → 评测仓 `environments/sql/seed.sql`（**环境是评测资产**） |
| `tests/diagnosis/test_sql_seed_contract.py` | → 评测仓 `tests/` |
| 11 题的 `verified_against` | 原样带入 golden 集，格式不变 |
| `test_case_meta.py` 的锁死数字 | → 评测仓 `dataset` 校验（manifest 哈希替代硬编码数字） |

### 9.2 环境归属（需要你确认的一个剩余决策）

**问题**：`seed.sql`、`sim_logs.py` 这类"环境定义"既被产品单测用，又被评测用。

| 方案 | 优点 | 缺点 |
|---|---|---|
| **(a) 评测仓拥有**（推荐） | 环境是 benchmark 的一部分，改环境=改 benchmark，必须版本化 | 产品单测要多一份 fixture |
| (b) 产品仓拥有，评测 import | 不重复 | 产品改 fixture 会**静默改变 benchmark** |
| (c) 产品暴露 `cloudagent testdata materialize` 命令 | 单一来源 | 多一层间接，且仍是产品控制 |

推荐 (a)。理由：**benchmark 的环境必须由 benchmark 拥有**；
产品单测需要的那点 fixture 是独立的小事，重复是应得的代价。

### 9.3 产品仓的最终形态

删除约 220 KB（评测代码 133.9 KB + 题库 91.1 KB）后，产品仓只保留：

```
cloudagent_ext/diagnosis/
  ├── {agent,session,runtime_session,gap_store,domain_gate,...}.py   # 产品逻辑
  ├── eval_support/{record,execute,cli}.py                            # ~35 KB 契约层
  └── （cases/ 与 evaluation/ 消失）
```

产品仓的单测从 860 个降到约 800 个（评测相关测试迁走）。

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| **生成题质量不达标**（GT 错、题同质） | 数据白造，指针反被污染 | P5 先做单域 PoC + 5% 人工抽检 + 多样性度量；不达标就回退手写 |
| **RunRecord 契约频繁变** | 两个仓反复返工 | schema_version + 只增不改 + 评测侧必须能读 N-1 版本 |
| **独立仓库同步成本高** | 开发体验变差 | 评测仓 pin 产品版本；开发期用 `pip install -e ../CloudAgent-public`；CI 里显式记录 git_sha |
| **历史 run 迁移不等价** | 新评分器不可信 | P2 以"逐题一致"为硬验收；不一致必须逐条解释 |
| **环境归属决策做错** | benchmark 被产品静默改变 | §9.2 按 (a)；manifest 里记录环境哈希 |
| **holdout 泄露** | RSI 结果不可信 | holdout 物理隔离（不进主仓）；canary 题检测 |

---

## 11. 决策记录（2026-11-07 全部落定）

| # | 问题 | 结论 | 影响 |
|---|---|---|---|
| **D-ENV**（原 §9.2） | 环境定义归谁 | **评测仓拥有** | `seed.sql` / `sim_logs.py` / `sim_sync_logs.py` 迁入评测仓 `environments/`；产品仓只保留自己单测需要的最小 fixture |
| **D-REPO**（原 §11.2） | 评测仓公开还是私有 | **私有** | holdout 可与主数据集同仓（省去加密/外置），但需**目录级访问纪律**（见 §4.1 修正） |

### 11.1 私有仓带来的两处设计修正

**修正 A：holdout 不再需要物理外置**

原设计假设"若公开，holdout 必须放别处"。私有仓下这个约束消失，但**纪律要求保留**：

```
云 agent-eval/
  datasets/
    golden/        # main split：跑评测用
    holdout/       # 隔离 split：**只在发布前/RSI 门禁时读**
                   # 纪律：CI 与日常命令只读 golden/；读 holdout 必须显式 --holdout 标志
```

关键防线从"物理隔离"变成 **"显式开关 + CI 默认拒绝"**：
- `cloudagent-eval run` 默认只加载 `golden/main`
- 加载 holdout 必须 `--holdout`，且该标志**不在任何 CI job 里出现**
- canary 题仍保留（检测是否被优化循环读到）

**修正 B：私有仓可以放真实环境快照，但仍要脱敏**

私有 ≠ 可以放凭据。`seed.sql` 不含密码（P1 已守住这条），
日志 fixture 的 PII 已由 `redact_sensitive` 处理。
**评测仓继承同样的脱敏纪律**：`environments/` 下不许出现任何 DSN / 密码 / 真实用户数据。

### 11.2 评测仓的物理位置（ZCode 需要知道）

```
本地路径：C:\Users\Administrator\Desktop\cloudagent-eval
```

- 先 `git init` 本地私有仓（不 push）
- 远程私有仓由项目所有者后续创建；**ZCode 不要尝试创建远程或 push**
- 与产品仓并列放在 Desktop 下，便于 `pip install -e ../CloudAgent-public` 开发

---

---

## 12. 与讨论稿的对应关系

| 讨论稿约束 | 本文落地位置 |
|---|---|
| R1 冻结集 | §4.3 manifest + §7 |
| R2 holdout | §4.1 / §7 R2 / §11.2 |
| R3 canary | §7 R3 |
| R4 低方差 | §6 统计层 |
| R5 成本门限 | §6.1 tier 预算 + §7 R5 |
| R6 快反馈 | §5.2-C 重评 + §7 R6 |
| R7 全链路版本化 | §3.2 subject/§5.2-C/§7 R7 |
| R8 不可被优化器读写 | §2.2 协议层隔离 |
