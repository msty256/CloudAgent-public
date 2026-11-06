# case 集体检报告（全 5 域，2026-11-01）

> 触发事件：`code-007` 重跑后 Top-1 命中率 0%，逐条核对发现**是 ground_truth 过期，不是诊断错**。
>
> **结论摘要**
>
> 1. 全 38 题里，**只有 15 题能在仓库内静态核实**（code 7 + log 6 + sync 2）；
> 2. 这 15 题里 **3 题过期**（`code-001` / `code-006` / `code-007`），过期率 20%；
> 3. 另外 **23 题（61%）无法静态核实**——缺 fixture 或描述的是外部项目。
>    这比"3 题过期"更值得警惕：**评测集的正确性目前无法在 CI 里保证**。

---

## 1. 判定标准

对每道题，把 `ground_truth.root_causes[].description` 当成一条**待验证命题**，去仓库里核对：

| 档 | 含义 |
|---|---|
| **有效** | 描述的行为在当前代码/数据上仍成立 |
| **过期** | 描述的行为已被改动推翻 |
| **待定** | 仓库里没有可核对的载体（缺 fixture / 外部项目 / 需运行期证据） |

"待定"不是"有问题"，而是"**没法在这里判定**"——但它和"过期"一样，都不能直接用于正确率指标。

## 2. 结论

> **口径修正（2026-11-01 二轮复核）**：第一轮把 sync-002/003 判成"待定"是**错的**——
> 它们的日志载体 `diagnosis/sync/fixtures/sim_sync_logs.py` 一直存在
> （`:46` TimeoutException、`:63` region mismatch），只是我当时只 grep 了 orders 和日志内容，
> 没查这个模块。已改为 `static`。sync-001 仍待定，但原因更正为
> **注释引用的 `seed.sql` 在仓库里不存在**，不是"没写 fixture"。

| 域 | 题数 | 有效 | 过期 | 待定 | 可核率 |
|---|---|---|---|---|---|
| code | 7 | 7（修复后） | 0（已修） | 0 | 100% |
| log | 6 | 6 | 0 | 0 | 100% |
| sql | 14 | 0 | 0 | **14** | 0% |
| cross | 6 | 0 | 0 | **6** | 0% |
| sync | 5 | 4 | 0 | **1** | 80% |
| **合计** | **38** | **17** | **0（3 题已修）** | **21** | **45%** |


## 3. 三题过期（code 域）

### 3.1 code-001：`InvestigationSession` 已接线（gt 说"零接线"）

gt 原文：

> InvestigationSession 仅定义在 diagnosis/session.py，生产代码**无任何外部调用点（零接线）**

当前代码：

```
cloudagent_ext/diagnosis/runtime_session.py:10  """把 InvestigationSession 绑到 ToolContext 上
                                                   （变更 wire-investigation-session）"""
cloudagent_ext/diagnosis/runtime_session.py:79  from ... import InvestigationSession
cloudagent_ext/diagnosis/runtime_session.py:131 session: InvestigationSession
```

**建议**：改 gt 或删题（报告 §5 有建议文本）。

### 3.2 code-006：`augment_agent_result` 不再"仅对 sql 生效"

gt 说"函数内部按 agent_type 早退、仅对 sql-diagnosis 生效"。

实际（`agent.py:1405-1413`）分派已上移到字典：

```python
_AUGMENTERS = {
    "sql-diagnosis": augment_agent_result,
    "code-diagnosis": lambda r, d: _augment_diagnosis_result(r, d, domain_label="code"),
    "log-diagnosis":  lambda r, d: _augment_diagnosis_result(r, d, domain_label="log"),
}
```

而 `augment_agent_result`（`sql_diagnosis.py:159-170`）只做转调、不再早退。

### 3.3 code-007：异步路径已经走后处理

gt 说"`is_async` 为真时提前 return，异步结果因此没有校验块"。
实际 `agent.py:1877-1895` 的注释直接说明这是**旧实现**、已由 `wire-investigation-session` 修掉。

**但确实存在另一处不对称**（子代理自己发现的，我已核实）：

```
_run_assessor 全仓只在同步分支被调用（agent.py:1388），异步分支 0 处
```

建议把 gt 换成这条——它测的是**当前真实**的缺陷，而且是阶段 2 引入核查器后产生的新边界。

## 4. 23 题为什么"待定"

### 4.1 sql 域（14 题）：**fixture 不在仓库**

`find . -name "*.sql"` 只找到 `tests/fixtures/sql/sync_seed_*.sql` 两个文件，
**没有任何 sql 域的 seed**。而 14 题里有 12 题的 gt 是"某列没有索引 / 计划里有某子串"
（如 `Seq Scan on orders`、`index_absent orders.tenant_id`），
这些既需要数据库、也需要 seed 数据才能核实。

含义：**sql 域无法在 CI 里校验，甚至无法复现**。

### 4.2 cross 域（6 题）：**描述的是外部项目**

gt 里出现 `TenantScopeFilter`、`deleteClueVersion`、`classification` 排序等 Java 侧符号：

```
grep TenantScopeFilter   → 本仓未找到
grep deleteClueVersion   → 本仓未找到
```

这些题描述的是一个**外部样本服务**（Java），仓库里没有它的代码。
除非那个项目以某种方式随仓提供，否则这 6 题的正确性只能靠人工记忆保证。

### 4.3 sync 域（1/5 待定）：**注释引用的 seed.sql 不存在**

- `sync-004` / `sync-005` **有效**：`tests/fixtures/sql/sync_seed_*.sql` 里 devices 上下游各 50 行（`generate_series(1,50)`）；
- `sync-002` / `sync-003` **有效**（第一轮误判，已纠正）：
  `diagnosis/sync/fixtures/sim_sync_logs.py:46` 有 `TimeoutException: batch window exceeded 60s`、
  `:63` 有 `tenant region mismatch expected=north actual=south`，与 gt 逐字对得上；
- `sync-001` **待定**：`sync_seed_primary.sql:7` 注释写"orders / customers 由既有 seed.sql 提供"，
  但 `tests/fixtures/sql/` 下只有 `sync_seed_primary.sql` / `sync_seed_secondary.sql`，
  **那个 seed.sql 不存在**。所以"orders 上游 50000 行"无处生成。

已在 `sync_seed_primary.sql` 头部补了说明（不自行灌数，理由见文件注释）。

## 5. 处置建议（待确认，未改任何文件）

### 5.1 三题过期

| 题 | 建议 | 备选 |
|---|---|---|
| code-001 | 改 gt 为"已在 `runtime_session` 接线，`get_or_create_runtime` 是唯一入口" | 删题（已修缺陷留题只会奖励背旧答案） |
| code-006 | 改 gt 为"由 `_AUGMENTERS` 按 `agent_type` 分派，三域各自转调 `_augment_diagnosis_result`" | — |
| code-007 | 改 gt 为"异步会做协议校验后处理，但**不执行 `_run_assessor`**，故 `assessments`/`gaps` 不回写" | — |

### 5.2 23 题待定

按"能不能补载体"分两类：

| 类别 | 题 | 建议 |
|---|---|---|
| 缺 fixture、可补 | sql 14 / sync 3 | 补 seed SQL（或生成脚本），并在 CI 里跑一次"gt 断言核查" |
| 外部项目 | cross 6 | 要么把样本项目作为 fixture 引入，要么在 gt 里标 `"external_evidence": true`，**不计入正确率** |

### 5.3 机制建议：给 gt 加校验元数据

```json
"ground_truth": {
  "verified_at": "2026-11-01",
  "verified_against": "agent.py:1877-1895 注释 + _AUGMENTERS 定义",
  "verification": "static"        // static | runtime | external
}
```

- `verified_at` 让"多久没复查"可见；
- `verification` 让"这题能不能自动校验"变成显式属性——**统计正确率时只算 `static` / `runtime` 的题**。

## 6. 最重要的结论

**1. 修复类改动会批量让用例过期。** 3 题过期里 2 题来自 `wire-investigation-session`、
1 题来自 `P3.6`——**改造越成功，过期的题越多**。所以"改完代码 → 体检受影响 case"应该是流程的一部分。

**2. 当前评测集的"可核率"只有 39%。** 这不是某道题的问题，是**整个评测装置的结构性问题**：
大部分题目依赖仓库外的环境与数据，无法在 CI 里保证正确性。
在补齐之前，任何"正确率"数字都只对那 15 题成立。

**3. 不能拿模型答案当标准答案。** 子代理这次答对了（它明确指出"观测来自历史版本"），
但**正因为它答对就改 gt，等于用被测对象定义正确性**。gt 只能人对着代码改，并写明依据。

## 7. 状态

| 项 | 状态 |
|---|---|
| 5 域 38 题核对 | **完成**（含一轮纠正） |
| 3 题 gt 修改 | **完成**（含 forbidden / observation_terms / recommendations 配套改） |
| 38 题加 `verification` 元数据 | **完成**（17 static / 15 runtime / 6 external） |
| 体检工具 + 守护测试 | **完成**（`case_audit.py` + `test_case_meta.py` 12 例） |
| sql 14 / cross 6 / sync-001 的载体 | **未做**（见 §8 的 P3/P4 与理由） |


---

## 8. 修复计划（2026-11-01 定，无模型额度，全程离线）

排序原则：**先做"能自证对错"的，再做"改了也不知道对不对"的。**

| # | 项 | 为什么排这个位置 | 是否烧额度 | 状态 |
|---|---|---|---|---|
| P0 | 改 3 道 code 题 gt + 加校验元数据 | 证据已在手（代码行号 + 注释），零风险 | 否 | **完成** |
| P1 | `verification` 字段语义 + 体检工具 + CI 守护测试 | 让"下次过期"能自动发现，否则改完还会烂 | 否 | **完成** |
| P2 | 修正 sync 三题判定（二轮复核推翻首轮结论） | 首轮误判 2 题，元数据必须纠正，否则比不标还坏 | 否 | **完成** |
| P3 | 补 sql 14 题的 seed | **本轮不做**：需要真实 PostgreSQL 才能验证索引/计划断言，没额度时补了也无法确认对错 | — | **不做** |
| P4 | cross 6 题 | **本轮不做**：缺的是外部 Java 项目，不是数据；引入它超出本次范围 | — | **不做** |
| P5 | 文档同步 + 记忆 | 保证后来者能看懂为什么这么改 | 否 | **完成** |

**P3 / P4 不做的理由要写进文档**，否则以后会有人以为"体检做完了就都修好了"——
实际上 **21 题仍然是待定状态**，只是这个状态现在被显式记录了。

### P0 的具体改法（依据已核实的代码）

| 题 | 新 gt 命题 | 依据 |
|---|---|---|
| code-001 | `InvestigationSession` 已在 `runtime_session` 接线，`get_or_create_runtime` 创建并绑定到 `ToolContext`，`decide()` 在派发前生效 | `runtime_session.py:10/79/131`、`agent.py:787` |
| code-006 | 分派由 `_AUGMENTERS` 字典按 `agent_type` 完成（三域），`augment_agent_result` 只转调 sql 实现、不再早退 | `agent.py:1405-1413`、`sql_diagnosis.py:159-170` |
| code-007 | 异步会做协议校验后处理（`augment_agent_text`），但**不执行 `_run_assessor`**，故 `assessments` 与缺口回写不发生 | `agent.py:1877-1895`、`_run_assessor` 仅 1388 一处调用 |

**配套还改了三处**——只改 `root_causes` 不够，这三题的 gt 里还有：

- `observation_terms`：证据要"看起来提到什么"，已按新命题重写；
- `forbidden_findings`：`code-001` 原本把"已接线"列为**禁止发现**、`code-007` 把"异步已覆盖校验"
  列为禁止——这两条现在都是**事实**，已反转；
- `acceptable_recommendations`：原本建议"去接线 / 去补校验"，都已做过，改为确认/复核类。

### 8.1 P1 的落地

| 产物 | 作用 |
|---|---|
| `case_library.VALID_VERIFICATIONS` | 值域 `static` / `runtime` / `external`，非法值直接报错 |
| `case_library._validate_ground_truth` | `static`/`runtime` 必须带 `verified_against`（不许空口说核过了） |
| `diagnosis/case_audit.py` | `python -m cloudagent_ext.diagnosis.case_audit`；**分开报"现在能核"与"有环境才能核"** |
| `tests/diagnosis/test_case_meta.py` | 12 例：字段必填、值域、static 需依据、**分布锁死**（17/15/6）、三题修复不许回退 |

最后一条是故意的：把某题从 `static` 偷偷降级成 `external` 会让测试红，逼人显式承认
"这题现在核不了了"——**没人会主动把坏消息写进报告**。

### 8.2 本轮体检自身的两处误判（已纠正）

| 误判 | 事实 |
|---|---|
| sync-002/003"缺日志载体" | `diagnosis/sync/fixtures/sim_sync_logs.py` **一直存在**，`:46`/`:63` 就是那两条事件 |
| sync-001"缺 orders seed" | 有注释但键错：`sync_seed_primary.sql:7` 说"由既有 seed.sql 提供"，**那个文件不存在** |

教训：**"缺载体"这个判断本身也要有证据**。我第一次只 grep 了 orders 和日志正文，
没查 `sync/` 目录，就把两题错标成 runtime——如果没做二轮复核，
这套元数据会比不标更误导。

---

## 9. 待办（明确登记，别让"待定"变成默认）

| 待办 | 影响 | 前置条件 | 登记时间 |
|---|---|---|---|
| **补 sql 域 seed，让 14 题从 `runtime` 变 `static`** | 正确率分母 17 → 31，sql 域首次可用 | 需要一个可写的 PostgreSQL 实例（本机或容器），因为 12 题的 gt 是"索引有无 / 计划含某子串"，只有真库能核 | 2026-11-01 |
| 补 `sync-001` 的 orders 50000 行 | sync 域 4 → 5 | 同上（并且要先决定"下游 orders 表不存在"时 `query_table_rows` 该返回什么） | 2026-11-01 |
| cross 6 题 | 需外部 Java 样本项目 | 决定是否把样本项目纳入仓库 | 2026-11-01 |

补 sql seed 的最低要求（写在这里，免得开工时重新想）：

1. 建 `cloudagent_ext/diagnosis/db/fixtures/` 或 `tests/fixtures/sql/` 下的 seed 脚本，
   覆盖 `orders`（5 万行）/ `customers`（2000 行）及其索引的**有/无组合**——
   12 题分别依赖 `tenant_id` / `created_at` / `customer_id` / `amount` / `status` 的缺失，
   以及 `idx_customers_region` 的存在；
2. seed 必须**幂等**（现有 `sync_seed_*.sql` 就是这个约定）；
3. 补完后把对应题的 `verification` 从 `runtime` 改成 `static`，并更新
   `test_case_meta.py` 里锁死的分布数字——**这一步是强制的**，否则测试会红，
   而这正是我们想要的效果。


