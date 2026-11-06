# 阶段 3 提案：上下文压缩补盲区 + 证据句柄

> 对应总纲 [`diagnosis-redesign.md`](../diagnosis-redesign.md) §4.4 与 §5「阶段 3」
> 前置：阶段 0（token / cache 度量）——采集代码已落地，**基线数字尚未采集**
> 状态：**T3.0–T3.5 全部实现（2026-11-01/03）**；T3.6 离线部分完成，
> **live 对照（cache 不回退）待额度**——且当前端点不返回 cache 字段，需先换端点
> 提案日期：2026-10-29 ｜ 决策更新：2026-10-29 ｜ 执行：2026-11-01 ~ 11-03

---

## 0. 一句话目标

让**取证大结果**（SQL 行集、日志块）在上下文里被"折"而不是被"丢"：
折成结构化摘要 + 一个可回取的句柄；压缩后仍能按需取回原文。

## 1. 起点：为什么现在这是个盲区

### 1.1 压缩的"清空"语义

`microcompact` 的机制是：超过 `keep_recent` 的旧工具结果，**内容替换成一句标记**：

```python
CLEARED_MESSAGE = "[Old tool result content cleared]"   # microcompact.py:45
```

而哪些工具可被清空，由一张**通用编码工具白名单**决定（`microcompact.py:48-60`）：
`Read / Bash / Shell / Grep / Glob / WebSearch / WebFetch / Edit / Write`。

诊断域实际用的取证工具**一个都不在名单里**：

```
get_schema / get_indexes / explain_sql / get_table_stats / get_lock_info / query_table_rows
```

也就是说：整条链路里产生最大结果的工具，恰好是完全不参与压缩的那批。

### 1.2 但"把取证工具加进白名单"是错的

因为白名单的语义是**清空**。取证结果被清空 = 证据没了 = 子代理失去已经查到的依据，
比不压缩更糟（它会把同一张表再查一遍）。

**这是本阶段的核心判断：我们要的是"折"，不是"丢"。**
两者在代码上是完全不同的动作：

| | 清空（现有） | 折叠（本阶段） |
|---|---|---|
| 结果 | `[Old tool result content cleared]` | 结构化摘要 + 句柄 |
| 证据 | 消失 | 保留要点，细节可回取 |
| 适用 | 可重新获得的中间产物 | 一次性取到的证据 |

### 1.3 触发全是"量驱动"

`context_collapse/trigger.py` 的三个触发（token 占比 / 413 报错 / 时间隙）都是
"涨到某个阈值就折"，**没有一个是看内容结构的**。所以一条 500 行的查询结果和一段 500 行的
报错日志，在触发器眼里没有区别。

---

## 2. 两个必须先讲清的设计问题

### 2.1 cache 约束的真实风险点，不是"压缩历史"

总纲写的是"不得破坏 prompt cache 前缀稳定性"。核了实现，这个约束的实际含义比字面窄：

`prompt_assembly.py:609-620` 的 `cache_control` 标记**只打在 system prompt 的 block 上**
（GLOBAL / SESSION / REQUEST 三个 scope group 各一块 + 一个动态边界块，最多 4 个标记）。
**历史消息上没有 cache 标记。**

所以：

- ✅ 压缩历史里的 `tool_result` **不影响** system 前缀的缓存命中；
- ⚠️ 真正的风险是**动 `tools` 数组**——同文件注释里写得很直白：
  "Adding/removing a single tool to a session WILL bust the prompt cache because the tools array
  changes the prefix"。

这条直接决定了"召回该怎么实现"（§2.2）。

### 2.2 召回的两条路，代价不同

| 方案 | 做法 | 代价 |
|---|---|---|
| A 新工具 | 加一个 `RecallEvidence(handle)` 工具 | **改 `tools` 数组** → 该会话的 system 前缀缓存一次性失效（之后稳定，不是每轮） |
| B 输出标记 | 模型输出 `[[RECALL: evh:sql:3]]`，loop 拦截并从存储取回注入 | 不改 tools；但要求 loop 支持"模型输出后处理" |

jiuwen 选的是 B（`ContextEngineConfig.enable_reload` 监听模型输出里的 `[[HANDLE:xxx]]`，
`compressor/base.py` 的归档摘要里带 `[[COMPRESSION_RECALL: id=…]]`）。

**这个选择必须先调研**：CloudAgent 的 `agent_loop_compat.py` 是否支持在模型输出后、下一轮前
插入内容。**支持 → 选 B；不支持 → 选 A 并接受一次 cache bust，或者本阶段先不做召回。**
这是 T3.0 的唯一任务，也是本阶段唯一可能推翻整体形态的点。

### 2.3 归档失败就不留句柄（"不传播"原则）

参照 `compressor/base.py:717-745`：归档（写存储）失败时，**不生成召回标记**，
压缩照常进行但摘要里不承诺"可回取"。

理由：留一个指向不存在的句柄，比不留更糟——模型会去取，取不到，然后浪费一轮。
这条与阶段 2 的"不宣称没核查的结论"是同一条原则。

---

## 3. 任务步骤

### T3.0 调研：loop 能否拦截模型输出（**先做，决定后续形态**）

**做什么**

1. 在 `query/agent_loop_compat.py` 里确认：模型返回文本后、下一轮请求前，有没有可挂载的
   处理点（hook / middleware / steer 机制）；
2. 确认 `QueryMiddleware`（`query/query_middleware.py`）是否可用于注入；
3. 把结论写进提案附录，并据此确定召回方案（A / B / 暂不）。

**验收**：一页结论 + 一条最小实验（手工构造一次带标记的输出，看能否注入）。

#### T3.0 调研结论（2026-11-01 完成，离线）

**问题 1：loop 有没有"模型输出后、下轮请求前"的改写钩子？——没有。**

- `on_event` 的类型是 `ToolEventHandler = Callable[[ToolEvent], None]`（`tool_system/renderers.py:64`）：
  **返回 None**，纯只读通知，事件只能被看、不能被改；
- 提案里提到的 `query/query_middleware.py::QueryMiddleware` **不存在**——
  那个文件里只有 `enforce_request_delay()` / `handle_rate_limit_error()`（限流与重试）。

**问题 2：唯一的改写点在哪？——`CompressionPipeline.run()`。**

```python
# services/compact/pipeline.py:183
async def run(self, messages: list[Message], input_token_count: int = 0) -> CompressionResult
```

它接收并返回 `list[Message]`，在每轮请求前执行，`microcompact` 是它的 Layer 3。
→ **T3.3 的结构归约就挂在这里**（Layer 3 之前），不需要碰 loop。

**问题 3：召回形态选 A（工具式），不是注入式。**

| 方案 | 为什么这样定 |
|---|---|
| 注入式（B） | 压缩那一刻**不知道模型下一步想看什么**，只能猜着注入——猜错就是纯浪费 |
| **工具式（A）** | 加一个只读工具 `recall_evidence(handle)`；不改 loop；调用天然带句柄参数，可观测可计数 |

**A 方案的连带代价（必须同一提交里处理）**：
新工具要进 `TOOL_SET_CODE_DIAGNOSIS` / `TOOL_SET_LOG_DIAGNOSIS` 白名单，
而 **`code-004` 的 gt 逐项列了白名单内容**（"仅含只读工具 Skill/Read/Glob/Grep/Bash/TodoWrite/
find_symbol/find_references"）——加工具会让这道题**过期**。
所以 T3.4 落地时必须同步更新 code-004 的 `root_causes` 与 `observation_terms`。
这正是 `docs/case-audit-2026-11-01.md` 说的"改造让 case 过期"，`case_audit` 就是为这种事准备的。

**附带发现（既有代码的边界，本阶段不修）**：
`microcompact_typed_messages(keep_recent=N)` 的实现是 `ids[:-N]`，
而 **`[:-0]` 在 Python 里等于 `[:0]`（空列表）**——
所以 `keep_recent=0` 不是"全清"，而是"**全不清**"。想用它关掉保留策略会静默失效。
（写测试时踩到了，记在这里免得下次再踩。）

**最小实验**：`tests/context/test_t30_compaction_probe.py`（5 例，全离线）

1. 9 个取证工具与 `COMPACTABLE_TOOL_NAMES` **零交集**（逐一断言），而 `Read/Grep/Bash` 在名单里；
2. 同一条 assistant 同时调 `Read` 与 `query_table_rows`，压缩后：**Read 被替换成
   `[Old tool result content cleared]`，`query_table_rows` 一个字节都没动**——
   盲区被实证：那批最大的结果既不参与压缩、也没有摘要，**既没省 token 也没省证据**；
3. `on_event` 签名只读；`CompressionPipeline.run` 是唯一改写点。


### T3.1 结构归约器（纯函数，确定性优先）

**做什么**

新增 `cloudagent_ext/context_system/reducers.py`，两个纯函数：

```python
def reduce_sql_rows(payload: dict, *, max_rows: int) -> Reduced
# 输入：query_table_rows / get_table_stats 的结果
# 输出：{columns, row_count, head: 前 N 行, tail: 后 N 行,
#        numeric_summary: {col: {min,max,mean,distinct}}, nulls: {col: count},
#        outliers: [...]}

def reduce_log_block(text: str, *, max_fingerprints: int) -> Reduced
# 输入：日志类工具结果
# 输出：{line_count, 时间范围, 按错误指纹聚类: [{fingerprint, count, first_ts, last_ts, sample}]}
```

硬约束：

- **必须保留头尾**（`head`/`tail`）——纯聚合会把"异常值恰好是唯一线索"的情况吃掉；
- **异常值单独提取**（数值列的 min/max 行、唯一的非空错误码）；
- **指纹聚类复用 `text_match.py` 的关键词抽取**（`extract_keywords`），不引入新分词依赖；
- 规则命中不了（非结构化文本）→ **返回 `None`，交由原有逻辑处理**，不强行归约。

**为什么不做 LLM 摘要**：论文 §2.2 明确"先确定性归约，归约不动了再用模型"。
LLM 摘要在本阶段列为可选档位（决策点 2），默认关闭。

**验收**：表驱动单测——行集/日志/非结构化各若干组，断言关键信息不丢（异常值、时间范围、条数）。

#### T3.1 执行记录（2026-11-01 完成）

产物：`cloudagent_ext/context_system/reducers.py`（`Reduced` / `reduce_sql_rows` /
`reduce_log_block` / `render_summary`）+ `tests/context/test_reducers.py`（38 例）。

**先修正一处提案里的事实错误**：原文写"一条 5000 行查询结果"，但
`diagnosis/db/tools.py:59` 的 `MAX_RESULT_ROWS = 200`、默认 `MAX_QUERY_ROWS = 20`，
**单次 `query_table_rows` 最多 200 行**。归约的收益来自**多轮累计**，不是单条超大——
这直接影响 T3.3 的阈值该按会话累计量算，而不是按单条长度算。

实测效果（200 行 / 5 列）：

```
SQL 行集   20176 字符 → 1338 字符（-93%）
日志块      3649 字符 →  287 字符（-92%）
```

**四类"不许丢"的信息**，每类都有专门用例：

| 信息 | 为什么不能丢 | 用例 |
|---|---|---|
| **离群行** | 纯 min/max/mean 会把"只有一行不对劲"吃干抹净，而那行常是线索 | `test_outlier_row_is_not_swallowed`（构造 amount=999999，断言它出现在 `extremes` 且能定位到行） |
| **头尾** | 首行常是"第一条/最早一条"，尾行是最新一条 | `test_head_and_tail_preserved` |
| **空值计数** | "这个字段一直是 NULL"常常就是根因 | `test_null_count_recorded` |
| **低基数分布** | status/类别列最有信息量 | `test_low_cardinality_distribution` |

**三个"不该折就不折"**：行数 < 20、aggregate 模式（只有一个 count）、
日志认不出时间戳或没有 ERROR/WARN 行——一律返回 `None`，调用方保留原文。
"折丢了"比"没折"严重得多。

**两个实现上的坑（都写了用例）**：

- `bool` 是 `int` 的子类，不能混进数值统计（`test_bool_is_not_a_number`）；
- 高基数列（如 `order_no` 200 个不同值）**不做分布**，否则摘要自身会爆炸。


### T3.2 证据句柄存储

**做什么**

1. 句柄命名 `evh:<domain>:<n>`（与 `Gap.evidence_refs` 的 `ev:sql:1` **分属两套**：
   前者是压缩产生的物理句柄，后者是子代理自报的证据标识，不能混用）；
2. 存储：`~/.cloudagent/evidence/<session_id>/<handle>.json`（原文 + 元信息：
   工具名、参数、生成时间、原始大小）；
3. 写失败 → 返回 `None`，调用方**不得**在摘要里写句柄（§2.3）；
4. 提供 `load_handle(session_id, handle) -> str | None`，只读、大小上限保护。

**为什么不用现有的 `CollapseStateFile`**：那套存的是"折叠的会话片段"（`save_store`/`load_store`），
粒度是消息批次；我们的句柄是单个工具结果，生命周期与清理策略都不同。**并存，不合并**。

**验收**：写读往返、写失败路径（只读目录）、大小超限拒绝。

#### T3.2 执行记录（2026-11-01 完成）

产物：`cloudagent_ext/services/compact/evidence_store.py` + `tests/context/test_evidence_store.py`（41 例）。

**四处实现决定，每处都有理由**：

| 决定 | 理由 |
|---|---|
| 根目录走 `get_user_config_dir()/evidence` | 复用既有约定，**尊重 `$CLOUDAGENT_CONFIG_DIR`**（与 sessions/reports 一致），不硬编 `Path.home()` |
| 文件名 `evh_<domain>_<n>.json`，句柄仍写 `evh:<domain>:<n>` | **Windows 文件名不允许 `:`**——句柄是逻辑标识，文件名是物理存储，不能混为一谈 |
| 原子写（`.json.tmp` → `os.replace`） | 崩在半截会留下坏 JSON，之后 `load` 返回 None 而不是报错，但数据白丢了 |
| `load()` 两层校验：白名单正则 + `resolve()` 后必须落在根内 | **句柄会写进提示、也可能被模型原样回传**。只做格式校验挡不住符号链接逃逸 |

**安全用例比功能用例多**，因为威胁模型很具体：一个能穿越目录的句柄读取，
等于给模型一个"读本机任意文件"的入口。测的输入包括
`../../etc/passwd`、`C:/Windows/win.ini`、`evh:..:1`、带 `\x00` 的串，
以及"归档目录里被人塞了符号链接"这种更难想到的情况。

**"不传播"原则的落实**：归档失败（目录建不了 / 超 4MB / 权限不足）一律返回 ``None``，
调用方据此**不在摘要里写句柄**——取不回来的句柄比没有句柄更糟，它会让模型
反复尝试召回一个不存在的文件。失败注入用例用"把 root 指向一个普通文件"来可靠触发，
不依赖平台的文件权限行为。

#### T3.2 补充：清理机制（2026-11-03）

初版只实现了"写/读/校验"，**没有清理**——没有过期时间、没有总量上限。
真实跑起来会一直堆，这是必须补的。

**策略：按会话整体过期**（`max_sessions = 20`），不逐文件淘汰。

理由：一次诊断的证据本来是一体的。留半个会话只会让句柄变成
"有时能取到、有时取不到"——**这比全删更让人困惑**，因为模型会以为是自己记错了。

**三条保守约束**（都有用例）：

| 约束 | 为什么 |
|---|---|
| 只碰根目录的**直接子目录**，`is_symlink()` 直接跳过 | 防顺着符号链接删到根外。有专门的用例在根外放一个"不能被删"的文件 |
| 删除失败**静默** | Windows 上文件可能被占用；删不掉就下次再删，绝不因为清理失败影响归档本身 |
| 清理放在 `save()` 的 `finally`，且再包一层 try | `finally` 里抛异常会**盖掉 `return handle`**——那才是最坏的结果 |

**也测了"不该删的东西"**：根目录下的散文件（不属于任何会话）不碰；
`max_sessions=0` 时整体禁用；根目录不存在时返回 0 而不是抛。



### T3.3 接入压缩管线

**做什么**

1. 在 `services/compact/pipeline.py` 的 microcompact 之前加一步"结构归约"：
   ```
   遍历 tool_result 消息（按工具名识别取证类）
     → 若长度超阈值（默认 2000 tokens）→ reduce_*
     → 归约成功 → 原文存句柄 → 替换成 [摘要 + 句柄标记]
     → 归约失败 → 原样保留（不退回 CLEARED_MESSAGE）
   ```
2. **不把取证工具加进 `COMPACTABLE_TOOL_NAMES`**——那张表的语义是清空，保持不动；
3. `compact.py` 的三处 `microcompact_messages` 调用保持不变（它们处理 dict 版消息，
   归约只做在 typed 路径，避免一次改两个 representation）。

**验收**：构造"一条 5000 行查询结果 + 6 条历史"的会话，压缩后：
内容显著变短、摘要里含 `evh:` 句柄、原文可通过句柄取回。

#### T3.3 执行记录（2026-11-01 完成）

产物三件：

| 文件 | 职责 |
|---|---|
| `services/compact/structural_reduce.py` | 接入层：遍历消息、识别取证结果、调归约器、写句柄、替换文本 |
| `services/compact/pipeline.py` | 新增 Layer 2.5（在 microcompact **之前**）+ 5 个 `sr_*` 配置项 |
| `services/compact/probe.py` | **CLI 探针**——回答"能不能在命令行验证" |

**分层理由**：归约器不知道消息、存储层不知道消息、接入层不知道磁盘细节。
三层各自可测——归约器不用造假文件系统，存储层不用造消息。

**实测（`python -m cloudagent_ext.services.compact.probe`）**：

```
会话字符数：20332 → 1464（-92.8%）
生效层：structural_reduce
结构归约：1 条，失败 0 条，省 18868 字符
句柄：evh:db:1
  evh:db:1 → 回取 20287 字符          ← 原文完整可取
摘要：amount min=10.0 max=999999.0 …   ← 离群值没被吃掉
```

加 `--no-sr` 对照：`20332 → 20332（0%）`、生效层为空——**这就是改造前的行为**。

**四条"不许发生"的用例**（比正向用例更重要）：

1. 归约失败**不得**退回 `CLEARED_MESSAGE`——那是丢证据
   （`pipeline.py:270-273` 的注释已经记着这个后果：模型被告知"参考之前内容"，
   而那份内容已被 erasure，只好重新 `cat`）；
2. 非取证工具（`Read`/`Grep`）的结果**一个字都不许动**——它们归 microcompact；
3. 已折过的结果**不得**二次折叠（幂等，看 `[已归约]` 前缀）；
4. 归档失败**不得**写出句柄（`test_store_write_failure_no_handle`）——
   用"root 指向普通文件"注入失败，不依赖平台权限。

**`max_items` 的由来**：改历史消息会让 prompt cache 失效，一次折太多等于把缓存全废掉。
默认 8 条，配合 `min_chars=4000`（太短的结果存句柄不划算，摘要未必比原文短）。

**探针为什么要存在**：压缩的默认门槛是 `gate_skip_ratio=0.6`（上下文到窗口 60%），
**普通会话根本到不了**——默认配置下在 REPL 里永远看不到压缩发生。
探针绕过门槛直接跑管线，是这一阶段唯一能"亲眼看"的入口。

#### T3.3 补充修复：`keep_recent`（2026-11-03）

**问题**：初版按 `max_items` 折，**不限新旧**。而压缩发生在"每轮请求前"——
于是**当轮刚查到的那 200 行也会立刻被折成摘要**，模型还没看过明细。
省 token 变成了拿诊断质量换。

**修法**：改两遍扫描——第一遍只收集候选（位置 + 内容），第二遍按"保护最新 `keep_recent` 条"
决定折哪些。默认 `sr_keep_recent = 2`（当轮 + 上一条）。

```python
if keep_recent > 0 and len(candidates) > keep_recent:
    reducible = candidates[:-keep_recent]
elif keep_recent <= 0:
    reducible = candidates          # ← 显式分支，见下
else:
    reducible = []
```

**为什么 `keep_recent=0` 要单独一个分支**：Python 里 `xs[:-0]` 等于 `xs[:0]`（空列表），
所以"全折"用切片实现会**静默变成"全不折"**。`microcompact` 那边踩过同一个坑
（见 T3.0 附录附记），这里显式判断避开。有专门的回归用例守着。

**这个修复改变了压缩率的口径**，必须一起说清：

| 口径 | 数字 | 含义 |
|---|---|---|
| 单条取证结果 | 20287 → 1365 字符（**-93%**） | 归约器本身的压缩能力 |
| 会话级（2 条结果、保护 1 条） | 40638 → 21770 字符（**-46.4%**） | **真实场景该看这个** |

之前的 "92.8%" 是**全部折**的极端情况。加上保护后同样规模只有 -46%，
因为会话里有一半内容本来就该保留。**汇报时用 -46% 更站得住**，
说 "-93%" 要加限定"单条结果、且该条已被判为可折"。

**探针同步改造**：现在构造两条取证结果（第一条"上一轮"、第二条"本轮"），
默认 `--keep-recent 1`，输出能同时看到"历史折了、本轮留着"：

```
会话字符数：40638 → 21770（-46.4%）
结构归约：1 条，失败 0 条，省 18868 字符
句柄：evh:db:1 → 回取 20287 字符
```



### T3.4 召回（形态由 T3.0 定）

按决策点 1 执行。无论哪种形态，都要记录 `recall_count` 与 `recall_miss`（句柄取不到）。

#### T3.4 执行记录（2026-11-01 完成，形态 = A 工具式）

产物：`services/compact/recall_tool.py` + 白名单接线 + `tests/context/test_recall_tool.py`（15 例）。

**两个实现决定值得记下来**：

**① 写入与读取必须共用同一个 session 解析。**
`evidence_store.resolve_session_id(tool_context)` 是唯一入口（诊断域优先取
`session.request_id`，否则 `ToolContext.session_id`）。
如果压缩时用 A 目录存、召回时用 B 目录读，症状极其隐蔽：**不报错，只是永远取不到**。
所以 `pipeline.py` 的 `_resolve_evidence_session_id` 直接转发到它，不自己实现一遍。

**② 装配走 `provision_with_recall()` 包装，不在域注册函数里加一行。**
域注册函数里有"已装配就 `return True`"的早退路径；直接在函数体内加注册会漏掉早退，
表现为"第二次装配后召回工具悄悄消失"。包装函数先跑域装配、再无条件补召回。

**错误信息的设计**（`test_recall_failures_tell_the_model_not_to_retry`）：
模型遇到失败的第一反应是重试。所以取不到时不能只说"失败"，要写清
**"不要重复尝试同一个句柄，请重新取证"**——把死路堵死，别让它白烧轮次。

**连带改动**：`code-004` 的 gt 必须同步更新——那道题逐项列了
`TOOL_SET_CODE_DIAGNOSIS` 的内容。已加上 `recall_evidence`，
并在 `verified_against` 记下依据（`policy.py:186-196`）。
**结论（"仅含只读工具"）不变**，只是清单多一项——这也是为什么它属于"过期"而不是"错"。

**未做**：`recall_count` / `recall_miss` 的统计。它们需要从 ``calls`` / ``events``
里数工具调用与 `is_error`，属于 T3.5 观测，一并做。

#### T3.4 补充修复：归档根目录也要一致（2026-11-03）

**发现的场景**：写 demo 演示召回时取不到原文。原因是
`_recall_call` 里硬编 `EvidenceStore()`（默认目录），而管线可以配 `sr_evidence_root`。
**两边一错开，句柄就成了废纸，而且不报错**——只表现为"取不到"。

这和我之前强调的 session 解析是**同一类故障**：坐标不能只统一一半。

**修法**：`ToolContext` 加 `evidence_root`，管线的 `_publish_stats()` 顺带把它写过去
（`sr_evidence_root` 配置了才写），召回端优先读它、否则走默认目录。

```python
root = getattr(context, "evidence_root", None)
store = EvidenceStore(root=root) if root else EvidenceStore()
```

**回归用例**：`TestCoordinatesMustMatch` 三条——
① 自定义根目录 + context 带 `evidence_root` → 取得到；
② 自定义根目录 + context 不带 → **取不到**（这就是要防的情形）；
③ 管线确实把 `sr_evidence_root` 写到了 sink 上。



### T3.5 观测

**做什么**

meta 增加：`compaction_before_tokens` / `after_tokens` / `handles_created` /
`reduce_failures` / `recall_count` / `recall_miss` / `cache_read_tokens`（阶段 0 已有采集口）。

#### T3.5 执行记录（2026-11-01 完成）

**数据怎么从管线程透到 meta**（这是本步唯一的难点）：

```
CompressionPipeline.run()
  → self._publish_stats(result.reduce_stats)      # 在 run() 外层统一收口
  → setattr(config.stats_sink, "compaction_stats", stats)
  → ToolContext.compaction_stats                  # slots 类，字段必须在类里声明
  → LiveExecutor.run_case 读出来进 meta
```

三个决定：

| 决定 | 理由 |
|---|---|
| 用 `stats_sink` 传引用，不改 `run()` 返回值 | 返回契约被多处依赖，改签名要动整条 query 链路 |
| 在 `run()` 外面包一层再写回 | `_run_layers` 里有 **5 处 early-exit 直接 return**，逐个加"写回"必漏 |
| `ToolContext` 加显式字段 | 它是 `slots=True`，`setattr` 新属性会直接报错（`runtime_session.py:453` 的注释也记着这条） |

**字段口径**：`meta.compaction`（管线写回的结构归约统计）+ `meta.recall_count` +
`meta.recall_miss`。三个一起看才有意义——**只报"折了几条"会让一个折完就取不回的管线
显得很漂亮**；加上未命中数，假象立刻破。

`_recall_stats()` 是纯函数：从 `tool_uses` 数调用、从 `events` 里按 `tool_use_id` 匹配
`is_error` 数未命中。只数 `recall_evidence` 自己的失败，别的工具失败不算。


### T3.6 回归与对照

| 类型 | 内容 |
|---|---|
| 必须全绿 | 现有 `tests/` 下 compact 相关用例；诊断域全套 |
| 新增 | `tests/context_system/test_reducers.py`、`test_evidence_handle.py` |
| 对照（需 live） | 同一组长案例（`code` 域 7 例）压缩开/关，比 **cache 命中率不回退** 与 token 降幅 |

#### T3.6 执行记录（2026-11-01，离线部分完成）

| 项 | 结果 |
|---|---|
| 现有 compact 相关用例 | **全绿** |
| 诊断域全套 | **全绿** |
| 新增用例 | reducers 38 + evidence_store 41 + structural_reduce 16 + recall_tool 15 + observability 8 + T3.0 探针 5 = **123 例** |
| 一次跑 `tests/{context,diagnosis,query,agent,tool}` | **1607 passed / 32 skipped / 59 subtests** |
| **live 对照（cache 命中率不回退）** | **未做——需要模型额度** |

**live 对照为什么必须单独做**：阶段 0 的实测显示该端点**不返回缓存字段**
（`cache_field` 为空），所以"cache 命中率"这个指标在当前端点上根本采不到。
真正的对照要用一个支持 prompt caching 的端点，否则这条比不了——
这件事已经写在阶段 5 提案 §2.0 的成本一节里。

**在这一步能确认的**：归约只改**历史**的取证结果、且每条只折一次（幂等）、
一轮最多折 8 条（`sr_max_items`）——这三点是 cache 不被大面积打散的前提。
"命中率到底回不回退"要等有 caching 的端点和额度。


---

## 4. 产出物

| 类型 | 路径 | 说明 |
|---|---|---|
| 调研 | 提案附录 | loop 是否支持输出拦截（决定 T3.4 形态） |
| 代码 | `context_system/reducers.py`（新） | 两个纯函数归约器 |
| 代码 | `services/evidence_store.py`（新） | 句柄读写 |
| 代码 | `services/compact/pipeline.py` | 接入结构归约 |
| 代码 | 召回接线（按 T3.0 结论） | 标记拦截 或 新工具 |
| 测试 | `tests/context_system/test_reducers.py` 等 | 归约 + 句柄 + 管线 |
| 文档 | 总纲 §4.4 状态更新 | 完成情况 + cache 实测数字 |

## 5. 依赖关系

**前置**：阶段 0 的 token 与 cache 采集（否则改完无法判断是否伤到命中率）。

**被谁依赖**：阶段 4（证据失效传播）在"回退"时要能指出"哪条证据被推翻"，
句柄提供了"证据原文可追溯"的基础——但不是硬依赖，阶段 4 可以只用 `evidence_refs`。

**与其他阶段的独立性**：本阶段可以独立于 1/2 推进（不改判定逻辑），
但按总纲的顺序约束，它排在 1/2 之后——因为 1/2 会改变注入段与调用次数，
先压缩再改判定会让"变短了"和"派得少了"两个因素混在一起。

## 6. 决策点（三个）

### 决策点 1：召回形态

| 选项 | 前提 | 代价 |
|---|---|---|
| **B 输出标记（推荐，若 T3.0 支持）** | loop 能拦截模型输出并注入 | 需要改 loop 的注入点 |
| A 新工具 `RecallEvidence` | 无前提 | tools 数组变化 → 会话首次 cache 前缀失效一次 |
| C 本阶段不做召回 | 无前提 | 句柄只用于"人类排查"，模型取不到 → 价值减半 |

推荐顺序：T3.0 结论支持 → B；否则 A；都不行 → C 并把"召回"延后。

> **已定（2026-10-29）：按 B → A → C 的优先序执行，具体落在哪一档由 T3.0 的调研结论决定。**
> 这条**故意不现在定死**——`agent_loop_compat.py` 是否支持模型输出后处理还没读过，
> 现在选一个就是猜。执行 T3.0 时按优先级取第一个可行的，并在附录记录为什么不选更高优先的那档。


### 决策点 2：是否允许 LLM 摘要兜底

| 选项 | 说明 |
|---|---|
| **只做确定性归约（推荐）** | 便宜、可测、不引入新失败模式；规则命中不了就原样保留 |
| 确定性 + LLM 兜底 | 覆盖更全，但每条大结果多一次调用，且摘要质量不可验证 |

推荐只做确定性：本阶段的目标是"补盲区"，不是"最优压缩比"。

> **已定（2026-10-29）：只做确定性归约，不做 LLM 摘要兜底。** 规则命中不了就原样保留。


### 决策点 3：句柄存储位置

| 选项 | 说明 |
|---|---|
| **独立目录（推荐）** | `~/.cloudagent/evidence/<session>/`，与折叠存储解耦，清理策略独立 |
| 复用 `CollapseStateFile` | 少一套存储，但粒度与生命周期都不匹配 |

> **已定（2026-10-29）：独立目录 `~/.cloudagent/evidence/<session>/`，与折叠存储解耦。**

---

## 10. 决策记录

| 时间 | 决策 | 影响 |
|---|---|---|
| 2026-10-29 | 召回形态按 **B → A → C** 优先序，执行 T3.0 时定 | 不预设结论；T3.0 的调研结果决定改不改 loop |
| 2026-10-29 | 只做确定性归约，不做 LLM 摘要兜底 | T3.1 只写纯函数；规则不命中就原样保留 |
| 2026-10-29 | 句柄存独立目录 | 新增 `services/evidence_store.py`，不复用折叠状态文件 |


## 7. 风险与应对

| 风险 | 表现 | 应对 |
|---|---|---|
| 归约吃掉唯一线索 | 摘要看着合理，但关键异常行没了 | 强制保留头尾 + 异常值提取；归约前后做"关键字段存在性"断言 |
| 句柄与现网数据不一致 | 模型按句柄取回的是快照，与当前库不同 | 句柄里写明"生成时间 + 原始参数"，摘要里标注"快照，非实时" |
| 加工具导致 cache 失效 | 命中率掉一截 | 若选 A，记录"失效仅发生一次"，并与关闭召回的臂对比；若选 B 则无此问题 |
| 改动面大（管线 + 多处调用点） | 连锁回归 | 只在 typed 路径（pipeline）接入，`compact.py` 的 dict 路径不动 |
| 归约后仍超预算 | 折完还是太长 | 归约后再走原有 microcompact 流程（两级：先折，折不动才清空） |
| live 对照成本 | 7 例 × 2 臂 | 复用阶段 0 的 L1/L2 单价估算；跑前确认 |

## 8. 工作量与顺序

这是总纲里唯一标"大"的阶段，主要成本在**改动面**（消息结构 + 管线 + 可能的 loop 注入点），
不在算法复杂度。

| 步 | 规模 | 依赖 live | 备注 |
|---|---|---|---|
| T3.0 调研 | 小 | 否 | **可能推翻召回形态，必须先做** |
| T3.1 归约器 | 中 | 否 | 纯函数，最需要设计测试 |
| T3.2 句柄存储 | 小 | 否 | 读写 + 失败路径 |
| T3.3 接入管线 | 中 | 否 | 只动 typed 路径 |
| T3.4 召回 | 中 | 否 | 形态由 T3.0 定 |
| T3.5 观测 | 小 | 否 | 复用阶段 0 采集口 |
| T3.6 对照 | 中 | **是** | 压缩开/关，比 cache 命中率与 token |

建议顺序：T3.0 → T3.1 / T3.2（并行）→ T3.3 → T3.4 → T3.5 → T3.6。

## 9. 完成的标准（本阶段出口）

1. **取证结果不再被丢**：压缩后该消息里有结构化摘要 + 句柄，不是 `[cleared]`；
2. **可回取**：按句柄能取回原文（或明确标注"不可回取"且不留假句柄）；
3. **cache 不回退**：压缩开/关两臂的 `cache_read_tokens` 对比不下降（若选方案 A，则记录一次性失效）；
4. **长案例 token 下降**：同一组长案例压缩前后 token 有可测的降幅。

至于"压缩是否让诊断更准"——**本阶段不回答**（压缩主要影响成本，对正确率的影响留给阶段 5 观察）。
