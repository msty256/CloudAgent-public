# EVAL-P1a 任务卡：RunRecord 契约 + `eval-run` 子命令

| 项 | 值 |
|---|---|
| 工作包 | EVAL-P1a |
| 状态 | `in_review`（完成待审；2026-11-07 ZCode） |
| 负责人 | ZCode |
| 仓库 | **产品仓** `C:\Users\Administrator\Desktop\CloudAgent-public` |
| 分支 | `feat/eval-p1a-runrecord` |
| 预估 | 1 天 |
| 依赖 | ✅ **EVAL-P0 已合并**（反向依赖已清零），可直接开工 |

> 设计依据：[`../design/eval-system-design.md`](../design/eval-system-design.md) §2–§3
> **字段级细节见 [`../design/eval-p1a-runrecord-schema.md`](../design/eval-p1a-runrecord-schema.md)**
> ——那份把 schema 细化到了可实现程度（字段名/类型/必填性/为空语义/映射表）。
> 开工前两针都要读：本卡说"做什么与不许做什么"，schema 说"字段长什么样"。

## 0. 先读这段：本卡到底在干什么

现在 `cloudagent_ext/diagnosis/evaluation/` 里的 `runner.py` 同时干三件事：
**执行 + 评分 + 报告**（134 KB）。评测仓要独立出去，但这三件事的耦合让拆分无从下手。

**RunRecord 契约**就是把其中"执行"这一半抽出来，定义成一个**稳定的、可序列化的磁盘格式**。
剩下两半（评分、报告）迁到评测仓。

**本卡只做"执行这半"**：跑一个 case → 写一份 JSON。**不评分、不聚合、不报告。**

## 1. 为什么这个契约重要（三条，按重要性排序）

### 1.1 它让产品收不到答案（防污染的结构性保证）

```python
@dataclass(frozen=True)
class RunRequest:
    schema_version: int = 1
    request_id: str = ""
    case_id: str = ""
    domain: str = ""
    question: str = ""          # ← 只有题面
    context: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)
    # ↑ 结构上没有 ground_truth / expected_agents / safety_expectations
```

对比现状：`cases/*.json` 整份放在产品包里，`runner.py` 同时持有题面与答案。
当前代码没有喂给模型，但**没有任何机制阻止将来有人这么做**。

RSI 循环里一旦优化器能读到答案，整个评测立刻失效。这条是**协议层防线**，不是风格偏好。

### 1.2 它让"改评分器不用重跑模型"

录一次 RunRecord，可以用不同评分器反复重算。这是评测仓能快速迭代的前提，
也是 EVAL-P2 等价性验证能做的原因（历史 16 次 run → RunRecord → 重算 → 逐题对比）。

### 1.3 它是产品仓甩掉 134 KB 的过渡桥

## 2. 写入范围

```
cloudagent_ext/diagnosis/eval_support/__init__.py       （新增）
cloudagent_ext/diagnosis/eval_support/record.py         （新增：纯 schema，零内部依赖）
cloudagent_ext/diagnosis/eval_support/execute.py        （新增：跑一个 case → RunRecord）
cloudagent_ext/diagnosis/eval_support/cli.py            （新增：eval-run 入口）
cloudagent_ext/cli/dispatch.py                          （注册 eval-run 子命令）
tests/diagnosis/eval_support/__init__.py                （新增）
tests/diagnosis/eval_support/test_record.py             （新增）
tests/diagnosis/eval_support/test_execute.py            （新增）
tests/diagnosis/eval_support/test_cli.py                （新增）
docs/collab/handoffs/eval-p1a-runrecord.md              （新增）
```

**不许动**：`diagnosis/evaluation/**`（P2 才删）、`agent/`、`query/`、`tool_system/` 的任何逻辑、
`permissions/` 的权限模式。

## 3. 三个必须守住的设计约束

### 约束 1：`RunRequest` 拒绝多余字段（不是静默忽略）

```python
def request_from_json(payload: dict) -> RunRequest:
    """严格校验。遇到未知字段（尤其 ground_truth）必须报错。"""
```

**为什么必须报错**：静默忽略会让"有人不小心把整份 case 文件传进来"这件事发生得无声无息。
症状是"评测跑得好好的，只是不知道为什么分数特别高"。

**用例要求**：传 `{"question": "x", "ground_truth": {...}}` → 抛 `RunRequestError`。

### 约束 2：`RunRecord` 只增不改 + 可降级

按设计 §3.2 的字段。三条规则：

1. `schema_version` 升级才允许破坏性变更；读取方必须能读 `N` 与 `N-1`
2. `mechanism` / `trace` **是 optional**：黑盒 subject 只填 `outcome` 也合法
3. **`usage.available == false` 时 token 字段为 `None`，不是 `0`**

第 3 条继承 `evaluation/cost.py` 已有纪律（"认不出的 usage 不能静默当 0"）。
现有 run.json 里已经吃过这个教训——报告里看不出"某臂省了 token"到底是真省了还是没采到。

`outcome.status` 六档，对齐现有 `CaseRun` 语义：

```
ok | timeout | crashed | empty | unfinished | invalid_output
```

### 约束 3：`execute.py` **允许临时复用 `evaluation.executors`**（技术债，P2 还）

```python
def execute_case(request: RunRequest) -> RunRecord:
    """跑一个 case，产出 RunRecord。

    ⚠️ 技术债（EVAL-P2 偿还）：
    当前复用 evaluation.executors.LiveExecutor 的装配与采集逻辑——它已能产出
    CaseRun（含 meta/calls/events/main_answer），本函数只负责 CaseRun → RunRecord 的转换。

    P2 要搬进本模块的函数清单（届时删除 evaluation/）：
      - _ensure_ready()          provider + registry + system_prompt 装配
      - build_diagnosis_tool_context()   dontAsk 受限上下文
      - _build_restricted_registry()     执行层白名单强制
      - build_main_dispatch_prompt()     main 模式系统提示
      - _agent_for_domain()              域 → 子代理映射
    """
```

**为什么不现在就搬**：那是一次 30 KB 的重构，会让本卡变成两个目标。
`eval_support → evaluation` **不构成分层倒置**（都在产品仓内），只是临时耦合。

**必须在 handoff 里列出上述清单**，否则 P2 会漏搬。

## 4. 具体做什么

### 4.1 `record.py` — 纯 schema，零内部依赖

只 import 标准库。这是本卡唯一"必须完全独立"的模块。

```python
SCHEMA_VERSION = 1

@dataclass(frozen=True)
class RunRequest: ...
@dataclass(frozen=True)
class RunRecord: ...

class RunRequestError(ValueError): ...

def request_from_json(payload: dict) -> RunRequest     # 严格校验，未知字段报错
def record_to_json(record: RunRecord) -> dict          # 稳定字段顺序（便于 diff）
def record_from_json(payload: dict) -> RunRecord        # 读 schema_version 1
```

### 4.2 `execute.py` — 跑一个 case

职责：
- 从 `RunRequest.options` 取 `dispatch_mode` / `grade_source` / `timeout_sec` / `permission_mode`
- 构造受限工具上下文（**复用现有 `build_diagnosis_tool_context()`，它已固定 `dontAsk`**）
- 跑 agent loop，收集 trace / mechanism / usage
- `CaseRun` → `RunRecord`

**不做**：任何评分、任何 GT 比对、任何 markdown。

### 4.3 `cli.py` + 子命令注册

```bash
cloudagent eval-run --request req.json --out rec.json
```

- 退出码：成功 0 / 请求非法 2 / 执行失败 1（**但仍写出 RunRecord**，`outcome.status` 标失败）
- stdout 只打一行摘要：`eval-run: <record_id> status=<status> elapsed=<n>s`
- 注册：在 `cli/dispatch.py` 的子命令 sieve 里加 `token == "eval-run"` 分支，
  照 `doctor` 的写法（`from cloudagent_ext.entrypoints.doctor import run_doctor` 那种薄入口）

### 4.4 测试（**全部零模型成本**）

| 文件 | 覆盖 |
|---|---|
| `test_record.py` | 往返逐字段相等；`RunRequest` 拒绝 `ground_truth`；读 `schema_version=1`；`usage.available=false` 时 token 为 `None` 非 0；`outcome.status` 六档全覆盖 |
| `test_execute.py` | 用 **fake executor**（注入一个返回固定 CaseRun 的桩）验证 `CaseRun → RunRecord` 的字段映射，**不调模型** |
| `test_cli.py` | `--request` 非法 → 退出码 2；成功路径 → 写出合法 JSON + stdout 摘要格式 |

**测试不许依赖真实模型或真实数据库。**

## 5. 验收命令

```powershell
# ① schema 往返（本卡核心）
python -m pytest tests/diagnosis/eval_support -q

# ② 无回归
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
# 期望：861 passed / 24 skipped（当前 main 基线）

# ③ 反向依赖仍为零（本卡不许引入新的）
python -c "
import glob, os
hits=[]
for f in glob.glob('cloudagent_ext/**/*.py', recursive=True):
    if '__pycache__' in f: continue
    if os.path.normpath(f).startswith(os.path.normpath('cloudagent_ext/diagnosis/evaluation')): continue
    if 'diagnosis.evaluation' in open(f, encoding='utf-8', errors='ignore').read(): hits.append(f)
print(hits)"   # 期望 []

# ④ lint（当前全仓已是 All checks passed，不许破坏）
python -m ruff check cloudagent_ext tests

# ⑤ 手动冒烟：不调模型的路径
python -c "from cloudagent_ext.diagnosis.eval_support.record import RunRequest; print(RunRequest(question='x'))"

# ⑥ （可选，烧额度）真跑 1 个 case —— 只跑 1 个
# 单例约 120 万 token，额度紧张可跳过并在 handoff 说明
```

## 6. 完成定义

- [ ] `eval_support/record.py` **零内部依赖**（只 import 标准库，可用 `grep`/import 检查证明）
- [ ] `RunRequest` 拒绝未知字段（含 `ground_truth`），有用例
- [ ] `RunRecord` 按设计 §3.2 输出，`outcome.status` 六档齐
- [ ] `usage.available=false` 时 token 为 `None`，有用例
- [ ] `record_to_json` 字段顺序稳定（两次序列化逐字节相等）
- [ ] `cloudagent eval-run --request ... --out ...` 可跑通，产出合法 JSON
- [ ] 端到端用 **fake executor** 覆盖（零模型成本）
- [ ] `tests/diagnosis` 无回归（861/24）；`ruff check cloudagent_ext tests` 仍 All checks passed
- [ ] 反向依赖扫描仍为 `[]`
- [ ] handoff 列明 **P2 要搬的函数清单**（5 个，见约束 3）

## 7. 红线

1. **不许把评分逻辑搬进 `eval_support`**。本卡只做执行与序列化。看到 `match_terms`、`top1`、`score` 就是越界。
2. **不许放宽 `dontAsk`**。这是全仓最重要的安全约束之一，E4 章节的 Bash 空返回问题
   （`KNOWN-ISSUE(eval-bash-empty)`）**也不在本卡修**。
3. **不许改 `evaluation/` 下任何文件**（P2 才动）。
4. **`RunRequest` 结构上不许有 `ground_truth`**，哪怕"只是存着不用"。
5. **真跑验证最多 1 个 case**。单例约 120 万 token，这是额度红线。
6. **不许为了让测试通过而 mock 掉"拒绝未知字段"这条** —— 它是本卡的安全价值所在。

## 8. 已知问题（**本卡不修，但要登记**）

`dontAsk` 权限模式下，子代理调 `Bash` 返回空字符串（`is_error=None`，内容空白），
模型于是自己总结成 "Bash is unavailable"，改用 Read/Grep/Glob。

影响：评测环境里任何需要跑命令的代码诊断都做不到，且**症状表现为"模型答不好"**
而不是"链路坏了"——这类误归因最伤评测信度。

**本卡不修**（属执行层改动，会和 P2 的迁移纠缠）。但要做两件事：

1. 在 `execute.py` 的 docstring 里记一条 `# KNOWN-ISSUE(eval-bash-empty)`
2. handoff 里单列，注明**建议在 EVAL-P3（修评分口径）一起修**

> 不写下来就会变成"没人记得的旧债"。
