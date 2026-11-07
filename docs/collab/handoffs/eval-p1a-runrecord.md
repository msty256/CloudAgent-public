# EVAL-P1a 交接说明：RunRecord 契约 + eval-run 子命令

> ZCode · 2026-11-07 · 分支 `feat/eval-p1a-runrecord`

## 复审修订（2026-11-07，按 eval-p1a-round1 裁决；**停在工作区未提交，等复验**）

一审 PASS 后按裁决做了一件事：**移除 `empty` 档，六档改五档**
`ok | timeout | crashed | unfinished | invalid_output`（空输出=没拿到作答机会，
归 `unfinished`，与 `scoring.categorize()` 口径一致）：

- `record.py`：`OUTCOME_STATUSES` 去掉 `"empty"`（注释记录裁决来由）；
- `execute.py`：`_determine_status()` 空输出分支改返回 `unfinished`；
  `case_run_to_record()` 的"要子代理结果但没拿到"分支同步改 `unfinished`；
- 用例同步：六档参数化 → 五档，空输出用例断言 `unfinished`，
  **新增 `test_rejects_removed_empty_status`**（写 `empty` 必红，防旧口径回流）；
- 本节之上正文里的"六档/empty"表述按交付时点保留原样（历史记录），以本节为准。

验证：eval_support **65 passed**（五档参数化 -1 + 拒绝用例 +1，净持平）、
诊断域全量 **926 passed / 24 skipped**、ruff 全绿。**未提交**——按审查 §7 等复验。
建议项（`# TODO(P2)` 标记）本轮未做，留待合并后与 P2 清单一起处理。

## 改了什么

| 文件 | 内容 |
|---|---|
| `cloudagent_ext/diagnosis/eval_support/record.py`（新增） | RunRecord v1 纯 schema：`RunRequest`/`RunRecord` 两个 frozen dataclass + 严格校验 + 稳定顺序序列化。**只 import 标准库**（AST 检查证明：仅 `dataclasses`/`typing`/`__future__`） |
| `cloudagent_ext/diagnosis/eval_support/execute.py`（新增） | `execute_case()`（跑 case → RunRecord）+ `case_run_to_record()`（纯映射）+ `build_subject()`（R7 身份）。docstring 登记 `KNOWN-ISSUE(eval-bash-empty)` |
| `cloudagent_ext/diagnosis/eval_support/cli.py`（新增） | `run_eval_run()`：退出码 0/2/1，失败**仍写出 RunRecord**，stdout 一行摘要 |
| `cloudagent_ext/cli/dispatch.py` | 子命令 sieve 注册 `eval-run` fast-path（doctor 同级，不加载 TUI/REPL） |
| `tests/diagnosis/eval_support/`（新增 4 文件） | 65 条用例，全部 fake 数据——**零模型、零数据库成本** |

## 三条设计约束的落地方式

1. **`RunRequest` 拒绝未知字段**：顶层与 `options` 两层都走白名单，`ground_truth` /
   `root_causes` / `expected_agents` / `match_terms` / `verification` 各有专门用例；
   `permission_mode` 白名单只有 `dontAsk`。
2. **`RunRecord` 只增不改 + 可降级**：`record_from_json` **容忍**未知顶层字段
   （"只增不改"允许不升版本加字段，读取方拒收会破坏同版本前向兼容）——与
   `request_from_json` 的严格拒绝**不对称是有意的**：request 是安全边界，
   record 是数据面。`usage.available=false ⇒ token=null` 有专门用例（含"写 0 即红"）。
3. **临时复用 `evaluation.executors`**：`execute_case` 只在无注入 executor 时
   构造 `LiveExecutor`；`run_case` 抛硬异常时构造最小 crashed CaseRun，
   让失败样本与成功样本走同一条序列化路径（契约"失败仍出记录"对硬异常也成立）。

**P2 要搬进本模块的函数清单**（任务卡约束 3 硬要求，届时删除 evaluation/）：

- `evaluation/executors.py::_ensure_ready()` — provider + registry + system_prompt 装配
- `evaluation/executors.py::build_diagnosis_tool_context()` — dontAsk 受限上下文
- `evaluation/executors.py::_build_restricted_registry()` — 执行层白名单强制
- `evaluation/executors.py::build_main_dispatch_prompt()` — main 模式系统提示
- `evaluation/executors.py::_agent_for_domain()` — 域 → 子代理映射

另：`_wants_subagent_grade()` 在 `execute.py` 里是**照抄的副本**（docstring 已注明），
P2 搬迁后应改为从唯一实现导入，防两处漂移。

## 验收结果

| 命令 | 结果 |
|---|---|
| `pytest tests/diagnosis/eval_support -q` | **65 passed**（record 39 / execute 18 / cli 8） |
| `pytest tests/diagnosis -q` | **926 passed / 24 skipped**（main 基线 861+24，+65 只增不减） |
| `ruff check cloudagent_ext tests` | **All checks passed** |
| 反向依赖扫描（任务卡 ③ 原命令） | `['...eval_support\\execute.py']` ——见规格疑问 1 |
| 反向依赖扫描（排除 eval_support 桥） | **`[]`**——除 sanctioned 桥外零引用 |
| 冒烟：`RunRequest(question='x')` / `eval-run --help` | 均正常（help 退出码 0） |
| ⑥ 真跑 1 个 case | **跳过**（单例约 120 万 token，额度红线；已按卡内"可跳过"条款在此声明） |

## 规格疑问（请 Lead 裁决）

1. **验收 ③ 的扫描命令与约束 3 自相矛盾**：约束 3 明文允许 `eval_support → evaluation`
   临时复用（"不构成分层倒置"），但 ③ 的命令只豁免 `evaluation/` 自身，
   必然把 `execute.py` 扫出来。我未改口径：上表同时贴了原命令结果与
   排除 eval_support 后的结果。建议 Lead 把豁免写进验收命令（或确认原样保留到 P2 还债）。
2. **empty 的归属**：schema §4.1 判定顺序把 `raw_output` 为空记为 `empty`（第 3 步），
   而现有 `scoring.categorize()` 把空输出归 `unfinished`。我按 §4.1（设计更新、
   且 P1a 本就不实现 unfinished 细分）；P3 对齐时需明确一处。
3. **`record_from_json` 对未知字段的容忍度**：按"只增不改"的版本规则推得"容忍"，
   但设计未明说。若 Lead 要求 record 也严格拒绝未知字段（与 request 对称），
   改动是一行 + 两个用例。

## 取舍与被否方案

- **status_provisional 只在 `ok` 时出现**（缺席即"最终判定"）：比恒出现该键的 diff 更小。
- **mechanism 白名单只搬 meta 里存在的键**：缺失键写 0 会重蹈"没采到冒充零消耗"
  的覆辙（与 usage 纪律同源）。
- **arm_env 只记 5 个机制开关的实际环境值**（未设置则缺席）：不 dump `os.environ`
  （凭据红线），不解析未设置的开关（避免发明语义）。
- **被否**：把 `unfinished`/`invalid_output` 判定提前进 P1a——违反红线 1
  （评分逻辑不得混入执行层），`status_provisional` 标记已为 P3 留好接口。

## 没做的事

- 未跑真实模型 case（额度红线，见验收表 ⑥）；
- 未动 `evaluation/**` 任何文件（红线 3；`_wants_subagent_grade` 是副本非迁移）；
- 未实现 `unfinished` / `invalid_output` 细分（P3 的评分层职责）；
- 未给 `eval-run` 增加 `--pretty` / 批量模式——本卡只有契约要求的最小面。
