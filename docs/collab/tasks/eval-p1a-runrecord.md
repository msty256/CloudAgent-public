# EVAL-P1a 任务卡：RunRecord 契约 + `eval-run` 子命令（产品侧）

| 项 | 值 |
|---|---|
| 工作包 | EVAL-P1a |
| 状态 | `ready` |
| 负责人 | ZCode |
| 仓库 | **产品仓** `C:\Users\Administrator\Desktop\CloudAgent-public` |
| 分支 | `feat/eval-p1a-runrecord` |
| 预估 | 1 天 |
| 依赖 | EVAL-P0（反向依赖已清） |

> 设计依据：[`../design/eval-system-design.md`](../design/eval-system-design.md) §2–§3

## 目标（一句话）

让产品仓能对**一个 case** 跑完诊断并输出一份**版本化的 RunRecord JSON**，
供独立评测仓消费。**不评分、不聚合、不报告**——那些全在评测仓。

## 为什么只做这么点

现在 `evaluation/` 里的 `runner.py` 同时干三件事：**执行 + 评分 + 报告**（134 KB）。
RunRecord 契约把其中"执行"这一半抽出来，定义为稳定接口；
剩下两半迁到评测仓。这一步只做"执行这半"的可序列化版本。

## 写入范围

```
cloudagent_ext/diagnosis/eval_support/__init__.py     （新增）
cloudagent_ext/diagnosis/eval_support/record.py       （新增：RunRequest / RunRecord schema）
cloudagent_ext/diagnosis/eval_support/execute.py      （新增：跑一个 case → RunRecord）
cloudagent_ext/diagnosis/eval_support/cli.py          （新增：eval-run 子命令入口）
cloudagent_ext/cli/dispatch.py                        （注册 eval-run 子命令）
tests/diagnosis/eval_support/test_record.py           （新增：schema 往返）
tests/diagnosis/eval_support/test_eval_run_cli.py     （新增：CLI 冒烟，mock provider）
docs/collab/handoffs/eval-p1a-runrecord.md            （新增）
```

**不许动**：`cloudagent_ext/diagnosis/evaluation/**`（P2 才删）、
`agent/`、`query/`、`tool_system/` 的任何逻辑。

## 三个必须守住的设计约束

### 约束 1：RunRequest 结构上不含 ground_truth

```python
@dataclass(frozen=True)
class RunRequest:
    schema_version: int = 1
    request_id: str = ""
    case_id: str = ""
    domain: str = ""
    question: str = ""
    context: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)
    # ← 这里永远不会有 ground_truth / expected_agents / safety_expectations
```

**这是防污染的结构性保证**：评测仓读 case 文件，只把 question+context 写进 RunRequest。
产品侧拿不到答案，就不可能在协议层泄露。

**验收要求**：`RunRequest.from_json()` 遇到多余字段（如 `ground_truth`）必须**报错拒绝**，
而不是静默忽略——静默忽略会让"有人不小心把整份 case 传进来"这件事发生得无声无息。

### 约束 2：RunRecord 只增不改 + 可降级

按设计 §3.2 的 schema。三条规则：

1. `schema_version` 升级才允许破坏性变更；读取方必须能读 `N` 与 `N-1`
2. `mechanism` / `trace` 是 **optional**：黑盒 subject 只填 `outcome` 也合法
3. `usage.available == false` 时**不许**把 token 写成 0（继承 `cost.py` 的纪律）

### 约束 3：本卡的 `execute.py` 允许临时复用旧执行器（**这是技术债，P2 还**）

`eval_support/execute.py` 的实现策略：

```python
def execute_case(request: RunRequest) -> RunRecord:
    """跑一个 case，产出 RunRecord。

    ⚠️ 技术债（P2 偿还）：当前复用 evaluation.executors.LiveExecutor 的装配与
    采集逻辑——它已经能产出 CaseRun（含 meta/calls/events）。
    本函数负责把 CaseRun 转成 RunRecord。
    P2 迁移时把 LiveExecutor 的装配逻辑搬进本模块，然后删除 evaluation/。
    """
```

**为什么允许**：避免本卡变成 30 KB 的重构。`evaluation/` 是产品仓内部代码，
`eval_support → evaluation` **不构成分层倒置**（都是产品仓），只是临时耦合。
必须在 docstring 与 handoff 里显式标记债务，并列出 P2 要搬哪些函数。

## 具体做什么

### 1. `record.py` — 纯 schema 模块，零内部依赖

```python
SCHEMA_VERSION = 1

@dataclass(frozen=True)
class RunRequest: ...
@dataclass(frozen=True)
class RunRecord: ...

def request_from_json(payload: dict) -> RunRequest      # 严格校验，多余字段报错
def record_to_json(record: RunRecord) -> dict          # 稳定字段顺序
def record_from_json(payload: dict) -> RunRecord        # 兼容 schema_version 1
```

**必须实现**：`RunRecord` 的 `outcome.status` 枚举与现有 `CaseRun` 对齐：
`ok | timeout | crashed | empty | unfinished | invalid_output`

### 2. `execute.py` — 跑一个 case

负责：
- 从 `RunRequest.options` 取 `dispatch_mode` / `grade_source` / `timeout_sec`
- 构造受限工具上下文（复用 `evaluation.executors.build_diagnosis_tool_context`，
  它已经固定 `dontAsk`——**不要放宽**）
- 跑 agent loop，收集 trace / mechanism / usage
- 返回 `RunRecord`

**不做**：任何评分、任何 GT 比对、任何 markdown 报告。

### 3. `cli.py` + 子命令注册

```bash
cloudagent eval-run --request <request.json> --out <record.json>
```

- 成功退出码 0；请求非法 2；执行失败 1（但**仍写出 RunRecord**，`outcome.status` 标失败）
- stdout 只打一行摘要（`record_id` / `status` / `elapsed`），便于脚本解析
- 注册方式：在 `cli/dispatch.py` 的子命令 sieve 里加一个 `token == "eval-run"` 分支
  （照 `doctor` 的写法：`from cloudagent_ext... import run_eval_cli; rc = run_eval_cli(rest_args)`）

### 4. 测试

| 文件 | 覆盖 |
|---|---|
| `test_record.py` | 往返（dict→dataclass→dict 逐字段相等）；`RunRequest` 拒绝 `ground_truth`；`RunRecord` 读 `schema_version=1`；`usage.available=false` 时 token 字段为 None 不是 0 |
| `test_eval_run_cli.py` | 用 **mock provider**（不调真模型）跑通端到端；断言产出文件是合法 JSON 且含必需字段；断言 stdout 摘要格式 |

**测试不许依赖真实模型**。用现有的 `evaluation.fixtures.offline_responses.json` 或自建 mock。

## 验收命令

```powershell
# ① schema 往返
python -m pytest tests/diagnosis/eval_support -q

# ② 端到端（mock provider，零模型成本）
python -m pytest tests/diagnosis/eval_support/test_eval_run_cli.py -q

# ③ 手动跑一次真实 case（会调模型，只跑 1 个 sql 题）
#    先准备 request.json（可以从 case 里抽 question + context）
python -m cloudagent_ext.cli.main eval-run --request /tmp/req.json --out /tmp/rec.json
# 期望：真实产出 RunRecord；outcome.raw_output 非空；usage.input_tokens > 0
# 注意：这一条要花约 120 万 token，只跑一次，不要批量

# ④ 无回归
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
# 期望：836 passed / 24 skipped

# ⑤ lint
python -m ruff check cloudagent_ext/diagnosis/eval_support cloudagent_ext/cli/dispatch.py
```

## 完成定义

- [ ] `eval_support/record.py` 零内部依赖（只 import 标准库）
- [ ] `RunRequest` 拒绝多余字段（含 `ground_truth`），有用例
- [ ] `RunRecord` 能按设计 §3.2 的字段输出，`outcome.status` 枚举齐 6 档
- [ ] `usage.available=false` 时 token 为 `None`，**不是 0**，有用例
- [ ] `cloudagent eval-run --request ... --out ...` 能跑通，产出合法 JSON
- [ ] 端到端用 **mock provider** 覆盖（零模型成本）
- [ ] 手动真跑 1 个 case 成功（**只跑 1 个**，贴输出到 handoff）
- [ ] `tests/diagnosis` 无回归；`ruff` 绿
- [ ] handoff 明确列出 **P2 要搬的函数清单**（技术债），以及"临时复用 `evaluation.executors`"的理由

## 已知缺陷：本卡**不修**，但必须记录

原 P4 的 T4.1 发现：**`dontAsk` 权限模式下，子代理调 `Bash` 返回空字符串**（`is_error=None`，
内容空白），模型于是自己总结成 "Bash is unavailable"，改用 Read/Grep/Glob。

影响：评测环境里任何需要跑命令的代码诊断都做不到，
且**症状表现为"模型答不好"，不是"链路坏了"**——这类误归因最伤评测信度。

**本卡不修它**，理由是：本卡只做契约与序列化，改权限/工具行为属执行层改动，
会和 `evaluation/executors.py` 的迁移（P2）纠缠。

**但要做两件事**：
1. 在 `eval_support/execute.py` 的 docstring 里记一条 `# KNOWN-ISSUE(eval-bash-empty)`；
2. 在 handoff 里单列，注明**建议在 EVAL-P3（修评分口径）一起修**——
   因为届时评测仓已经能看懂"这条输出为什么空"，修完还能量化影响。

> 这条不是遗漏，是**有意识的延后**。不写下来就会变成"没人记得的旧债"。

## 红线

1. **不许把评分逻辑搬进 `eval_support`**。本卡只做执行与序列化。
2. **不许放宽 `dontAsk` 权限模式**。全仓最重要的安全约束之一。
3. **不许改 `evaluation/` 下的任何文件**（P2 才动）。
4. **RunRequest 不许接受 ground_truth**，哪怕"只是存着不用"——结构上就不该有。
5. 真跑验证**只跑 1 个 case**。这是额度红线（单例 ~120 万 token）。
