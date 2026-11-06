# 基线尝试记录（2026-11-03）

> 目标：阶段 0 的 T0.7 —— 跑 code 域基线，作为阶段 5 对照的分母。
> 结论：**没跑出来**。三次尝试全部无效，根因是**端点限流**，不是代码。
> 花掉约 **480 万输入 token**（21 万 + 273 万 + 170 万 + 27 万）。
> 但过程中确认了三件有价值的事，见 §4。

---

## 1. 三次尝试

| # | 命令 | 结果 | 耗时 | 输入 token |
|---|---|---|---|---|
| 1 | `--timeout-per-case 180` | `invalid_output` | 41s | 21 万 |
| 2 | `--timeout-per-case 300` | `crashed: timeout after 300s` | 300s | 273 万 |
| 3 | `--timeout-per-case 480` | `invalid_output`（`dispatch_incomplete=True`） | 约 480s | 170 万 |

三次都是 `code-001`，`--dispatch main`，`--grade-source auto`。

---

## 2. 第一次：主 Agent 没等结果就收尾（**已修**）

`raw_output` 是散文，不是协议 JSON：

> "三项取证已并行启动：两条静态链路追踪和一条测试执行核查。**等子代理返回带行号的证据后，我再给出结论。**"

trace 显示主 Agent 用 `run_in_background: true` 派了 3 个子代理，轮 6/7/8 在轮询，
轮 9 说了上面那句话就结束了。于是 `subagent_results` 为空 → `grade_source` 退回 `main` →
评分拿到散文 → `invalid_output`。

**这是 P1 约束的残留缺口**：约束教会了主 Agent"要委派"，但没约束"必须等结果"。

**修法（已做）**：

1. `_MAIN_DISPATCH_CONSTRAINT` 加第 5 条：委派时不要设 `run_in_background`，子代理返回前不给结论；
2. `meta.dispatch_incomplete` 新字段：`delegations > 0 and 没有子代理 payload` 时为 True。
   这样"派了但没跑完"能被单独统计，**不混进正确率分母**——否则看起来像诊断失败。

---

## 3. 第二、三次：端点限流（**外部阻塞**）

第二次跑满 300s 超时；第三次子代理返回的是：

```
Rate limit exceeded. Please wait and retry.
```

trace 里出现 3 次。子代理被限流打挂 → 没有协议结果 → `dispatch_incomplete=True`。

**这不是代码问题**。当前端点（`api-inference.modelscope.cn`）在并发子代理场景下限流明显——
一次诊断会派生 3–5 个子代理并发调用，很容易撞上。

---

## 4. 三次尝试确认的三件事

### 4.1 单例真实成本：**273 万输入 token / 300s+**（同步等待后）

第一次 41s / 21 万是**假象**——那是不等结果的快速收尾。
真跑完整流程（3 子代理 + 66 次模型调用 + 105 次工具）是 **273 万 / 5 分钟以上**。

对比之前 `code-007` 实测 326 万 / 350s，量级一致。**所以同期估算的"3 例 × 4 臂 ≈ 3900 万 token"要上调**：
按 280 万/例、单臂单轮算，3 例 × 4 臂 = 12 次单例 ≈ **3400 万**，加上超时重试和限流重跑，
实际准备 **5000 万–8000 万**更稳妥。

### 4.2 同步等待是必须的，代价是单例时间翻 7 倍

`180s` 超时一定不够。**`--timeout-per-case` 至少要 480s**，建议 600s。

### 4.3 本机环境其实已经就绪（**意外收获**）

`~/.cloudagent/config.json` 里已经配好：

```
CLOUDAGENT_DB_DSN = postgresql://cloudagent_ro:...@127.0.0.1:5433/cloudagent_sim
CLOUDAGENT_LOG_ROOT = <本机路径>\logs-sim
```

实测连上（5433 可达），库里有数据：

| 表 | 行数 |
|---|---|
| `public.customers` | **2000** |
| `public.orders` | **50000** |
| `public.devices` | 50 |
| `public.tenants` | **0（空）** |

**也就是说 sql 域的 seed 大部分已经存在**，`needs-quota.md` 里"需要一个可写 PG"这条可能不成立——
真正要做的是**逐题核对 seed 是否满足各题的依赖**（哪些题缺 `tenant_id` / `created_at` /
`customer_id` / 索引），而不是从零建库。这一步**不花模型额度**。

`tenants` 为空值得注意：依赖租户表的题目会失败。

---

## 5. 顺带发现但没修的问题

### 5.1 子代理里 `Bash` 返回空

trace 里子代理调了 `ls`，返回的是**空字符串**（`is_error=None`，内容空白），
于是模型自己总结为"Bash is unavailable in this session，我改用 Read/Grep/Glob"。

影响：任何需要跑命令的代码诊断（比如执行测试）在评测环境里都做不到。
`TOOL_SET_CODE_DIAGNOSIS` 里**是有 `Bash` 的**，所以这不是白名单问题，
要查执行环境（cwd / sandbox / 权限模式 `dontAsk`）。

### 5.2 进程退出时 `cannot schedule new futures after shutdown`

超时收尾时后台的 tool-dispatch 线程还在跑，进程退出后报这个。不影响结果，但日志很脏。

---

## 6. 要跑通基线，需要什么

| 阻塞 | 解决方式 |
|---|---|
| **端点限流** | 换一个不限制并发的端点，或付费额度。**这是硬阻塞** |
| 单例 5 分钟 + 280 万 token | 预算按 **5000 万–8000 万**准备（3 例 × 4 臂 + 重试余量） |
| 超时参数 | `--timeout-per-case 600` |
| `Bash` 返回空（5.1） | 建议先修，否则 code 域"跑测试取证"这条路是断的 |

**建议顺序**：先修 5.1（离线可查）→ 换端点 → 跑 L1（1 例）确认非零 →
再决定 L3 规模。否则每次尝试都是 300 万 token 的赌博。


---

## 7. 换端点之后的 5 次尝试（2026-11-03 22:44–23:09）

换到火山 ark（`api/plan/v3` + `deepseek-v4-flash`）后继续排查，又修了 3 个缺陷，
但仍未拿到有效基线。**累计约 2000 万输入 token**。

| # | 现象 | 根因 | 状态 |
|---|---|---|---|
| 4 | `calls=0 / empty output` | `_default_provider_factory` 硬编 `"deepseek"`，改 `default_provider` 不生效 | 已修 |
| 5 | direct 模式答"数据库不可达" | direct 硬编 `sql-diagnosis`，拿 code 域的题问 SQL 代理 | 已修（`_DOMAIN_TO_AGENT`） |
| 6 | `[Max tool turns reached]` | direct 模式 `max_turns=14`，26 次工具调用即撞顶 | 已修（48/36） |
| 7 | 输出截在半句话、无 json 块 | 模型查了 49 次工具仍在读代码，未收口 | **未修**：撞顶/截断应单独归类为 `unfinished`，不该混进 `invalid_output` |
| 8 | main 模式子代理结果无法解析 | 入账文本被截断，`_recover_if_truncated` 未恢复 | **未修** |

### 这一轮最重要的结论

**7 个问题里有 6 个是评测链路自己的缺陷，只有第 7 个是模型能力。**
但它们的症状**全部表现为 `Top-1 = 0%` / `invalid_output`**——
如果不逐个拆开，会直接得出"这个模型诊断能力不行"的错误结论，
而实际情况是**它连一次完整的答题机会都没拿到**。

这也是为什么必须先跑 L1 探路：**在链路没验证之前，任何 baseline 数字都是假的。**

### 下一步（按性价比）

1. **把 `[Max tool turns reached]` / 截断输出单独归类**（离线，10 分钟）——
   否则 baseline 里会混进大量"假失败"；
2. **修 main 模式的截断恢复**（离线，要查 `transcript_path` 是否可用）；
3. 修完再跑 L1；L1 出非零指标后，才值得跑多例。


---

## 8. 第二次收敛（23:19–23:35）

做了两件离线的事，并把问题收敛到**一个核心点**。

### 8.1 新增 `unfinished` 类别（已做）

`scoring.categorize` 现在区分：

| 类别 | 含义 | 例 |
|---|---|---|
| `unfinished` | 没拿到完整作答机会 | 撞轮数上限（`[Max tool turns reached]`）、空输出 |
| `invalid_output` | 答完了但不符合协议 | 给了完整散文、没有 JSON 块 |

**仍计入正确率分母**（不美化指标），但单独计数、单独展示。

试过的弯路：一开始用"长度 < 1500 且不含 `{` 就算截断"，结果把离线样例里
一个完整的短回答（"抱歉无法完成。"）误判成没跑完——**离线用例当场抓到**。
改成只认可靠信号（撞顶信标 + 空输出），不靠长度猜。

### 8.2 强化输出契约（已做）

`_RESULT_CONTRACT` 从"末尾一个 json 块、前面可以写分析"改成
"**只能是一个 json 代码块**，不要任何过程叙述、不要英文思考"。

原因：实测子代理会输出 `Now let me examine the key tests…` 这种过程就收尾。

### 8.3 问题收敛到一个点

第 11 次 live，主 Agent 这次**真的等到并整合了子代理结论**（1915 字符，内容正确：
"生效，但按 agent 类型分叉…"）。但：

```
grade_source: main        ← 仍退回 main
dispatch_incomplete: True ← 子代理结果没进账本
```

**根因锁定：子代理的结果没有写进 `session.entries[].result`。**
佐证：trace 里能看到 `diagnosis-protocol 校验：FAILED`，
events 里 Agent 的 `tool_output` 长度是 **0**。

也就是说 `_tool_result_text(result)` 取不到 Agent 工具的输出。
这是 `grade_source=subagent`（P2 修复的核心）一直拿不到数据的根因。

### 8.4 下一步（明确、且不需要模型额度）

在 `_ledger_text` / `_tool_result_text` 处加日志，打印 `result.output` 的实际结构，
确认是「字段名不对」还是「内容被清空」。**这一步纯离线**，确认后再跑 live。
