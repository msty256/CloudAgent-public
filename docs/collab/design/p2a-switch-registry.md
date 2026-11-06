# P2a 实施规格：开关登记表与机制守卫（**产品侧**）

> 状态：`approved` · 设计：DSH Lead（2026-11-07）· 实现：ZCode
> 任务卡：[`../tasks/p2a-switch-registry.md`](../tasks/p2a-switch-registry.md)
> **范围变更**：本包只做**产品侧**。原 P2 的评测侧（`runner.py` 泄漏守卫参数化）
> 已并入新评测体系治理层，**不在本包**。理由见 [`p1-p4-vs-eval-system.md`](./p1-p4-vs-eval-system.md)。

---

## 1. 问题陈述（一句真 bug + 一个结构性缺陷）

### 真 bug：`CLOUDAGENT_GAP_INJECTION=false` 关不掉注入

```python
# cloudagent_ext/tool_system/tools/agent.py:175-182
def gap_injection_enabled() -> bool:
    return os.environ.get("CLOUDAGENT_GAP_INJECTION", "on").strip().lower() != "off"
```

它**只认字面量 `"off"`**。写 `=false` / `=0` / `=no` 都会**继续注入**。

对比 `switches.env_flag()` 认 8 种假值（`0/false/no/off/n/f`）——
两个开关用两套语义，而其中一套是错的。

**后果**：做对照实验时，如果你按直觉写 `CLOUDAGENT_GAP_INJECTION=false`，
"实验组"和"对照组"实际都在注入。**数据全废，而且完全没有报错。**

这不是理论风险：`runner.py` 的 preset 用的是 `"off"` 所以没暴露；
但任何人在 shell 里手动设置就会踩中。

### 结构性缺陷：5 个开关，3 套读取方式

实测全仓（排除 `evaluation/`，那是待删代码）：

| 开关 | 语义 | 读取位置 | 是否走 `switches.py` |
|---|---|---|---|
| `CLOUDAGENT_CONTEXT_REDUCE` | bool | `switches.py:65` | ✅ 走 `env_flag` |
| `CLOUDAGENT_EVIDENCE_INVALIDATION` | bool | `switches.py:71` | ✅ 走 `env_flag` |
| `CLOUDAGENT_GAP_INJECTION` | bool | `agent.py:182` | ❌ 自己读，语义不一致 |
| `CLOUDAGENT_DOMAIN_GATE` | 三档 `off/same_target/strict` | `runtime_session.py:440` | ❌ 自己读 |
| `CLOUDAGENT_GOAL_STOP_STRATEGY` | 三档 `agent_report/transcript/hybrid` | `assessor.py:126` | ❌ 自己读 |

**三个自己读的，就有三套"非法值怎么办"的策略**（虽然目前都是回退默认，但没统一）。

`switches.py` 的模块 docstring 自己写着：

> 第 2 条最容易被破坏：开关加在三个地方，其中一处忘了判断，
> "关了"只是半关，对照结果就是脏的——而且从数据上完全看不出来。

**这个仓库正在犯自己文档里警告的错误。**

---

## 2. 要做什么（三个 T，全部离线可验证）

### T2a.1 建开关登记表

在 `cloudagent_ext/diagnosis/switches.py` 里新增（**现有 3 个公开函数保持不变，21 个既有用例必须全绿**）：

```python
@dataclass(frozen=True)
class SwitchSpec:
    name: str                      # 逻辑名，如 "gap_injection"
    env: str                       # 环境变量名
    kind: str                      # "bool" | "mode"
    default: Any                   # True/False 或 "same_target"
    modes: frozenset[str] = frozenset()   # kind=="mode" 时的合法值
    off_value: Any = None          # "关"的取值：bool→False，mode→"off"
    #: 关掉后**应当消失**的可观察行为（人话）。守卫用例按它写，报告按它展示
    off_effect: str = ""

SWITCHES: dict[str, SwitchSpec] = { ... }   # 5 条

def is_off(name: str) -> bool: ...
def current(name: str) -> Any: ...            # 当前生效值
```

**5 条登记内容**：

| name | env | kind | default | off_value |
|---|---|---|---|---|
| `context_reduce` | `CLOUDAGENT_CONTEXT_REDUCE` | bool | `True` | `False` |
| `evidence_invalidation` | `CLOUDAGENT_EVIDENCE_INVALIDATION` | bool | `True` | `False` |
| `gap_injection` | `CLOUDAGENT_GAP_INJECTION` | bool | `True` | `False` |
| `domain_gate` | `CLOUDAGENT_DOMAIN_GATE` | mode | `"same_target"` | `"off"` |
| `goal_stop_strategy` | `CLOUDAGENT_GOAL_STOP_STRATEGY` | mode | `"hybrid"` | `"agent_report"` |

⚠️ 注意最后一条：`goal_stop_strategy` 的"关"不是 `"off"`（它不是三档里的值），
而是 `"agent_report"` ——那是**核查器不跑**的档位。这一点必须在 `off_effect` 里写清：
`"独立核查器不运行（assessor 不触发）"`。

### T2a.2 `gap_injection_enabled()` 改走登记表（**修 bug**）

```python
# cloudagent_ext/tool_system/tools/agent.py
def gap_injection_enabled() -> bool:
    """缺口注入开关。

    **不在模块导入时求值**：配置/环境注入发生在启动之后，模块级常量会固化成默认值。
    读取统一走 ``switches`` 登记表——修前这里只认字面量 "off"，
    写 "false"/"0"/"no" 会静默继续注入（对照实验数据全废且无报错）。
    """
    from cloudagent_ext.diagnosis.switches import env_flag, SWITCHES
    return env_flag(SWITCHES["gap_injection"].env, True)
```

**这是语义变更，必须在 handoff 单列**：`=false` / `=0` / `=no` 从"无效"变成"关闭"。
这是**修复**，不是回归——但要让 reviewer 知道。

同时把 `domain_gate_mode()`（`runtime_session.py:440`）和
`assessor_strategy()`（`assessor.py:126`）改成**从登记表取 env 名与合法值**，
但**保留各自的非法值告警逻辑**（它们现在会 `logger.warning` 后回退默认，
这个行为是好的，别删）。

### T2a.3 每个开关一条"关掉 ⇒ 行为消失"的守卫

新建 `tests/diagnosis/test_switch_guards.py`，**参数化遍历 `SWITCHES`**，
每个开关至少一条"机制层"断言（不是断言开关读到了什么，是断言**行为不同**）：

| 开关 | 守卫方式 | 离线可行 |
|---|---|---|
| `context_reduce` | 开：`CompressionPipeline` 对大结果产出压缩统计；关：不压缩、内容原样 | ✅ 已有 `test_switches.py` 的先例可抄 |
| `evidence_invalidation` | 开：`conflict` 使 resolved 退回 open；关：状态不变 | ✅ 已有先例 |
| `gap_injection` | 开：`_with_current_state()` 返回的 prompt 含缺口段；关：不含 | ✅ 构造 fake runtime 即可 |
| `domain_gate` | `off` 档：`runtime.domain_gate()` 对"同目标 blocked"返回 None；`same_target` 档：返回停判 | ✅ 纯函数 |
| `goal_stop_strategy` | `agent_report` 档：`should_verify()` 返回 False；`hybrid` 档：按间隔返回 True | ⚠️ **只守策略函数**，不守"核查器真的没跑"（那需要模型） |

**`goal_stop_strategy` 的诚实边界**：离线只能守到
"`assessor_strategy()` 解析正确 + `should_verify()` 在该档返回 False"。
**"核查器确实没被调用"需要 live 才能验**——这条要在 handoff 里明确写：
`test_switch_guards.py` 对该开关只覆盖策略层，不覆盖执行层。

⚠️ **不许造假的守卫**：写一个永远会过的断言（比如只断言 `is_off()` 返回 True）
等于没守。判据是：**把开关的读取逻辑故意改坏，这条守卫必须红**（自己在本地验一次）。

### T2a.4 更新 `switches.py` 模块 docstring

把"每加一个机制开关，都要同时加守卫用例"这句升级成可操作的流程：

```
1. 在 SWITCHES 里登记（env / kind / default / off_value / off_effect）
2. 读取点必须走 is_off() 或 current()，不许自己读 os.environ
3. 在 test_switch_guards.py 里加一条"关掉 ⇒ 行为消失"的用例
```

---

## 3. 验收标准

```powershell
# ① 既有 21 例开关语义用例必须原样全绿（不许改它们的期望值）
python -m pytest tests/diagnosis/test_switches.py -q

# ② 新增守卫
python -m pytest tests/diagnosis/test_switch_guards.py -q

# ③ 真 bug 修复验证（这条是本包存在的核心理由）
$env:CLOUDAGENT_GAP_INJECTION="false"
python -c "from cloudagent_ext.tool_system.tools.agent import gap_injection_enabled as f; print('false ->', f())"
# 期望：false -> False   （修前是 True）
$env:CLOUDAGENT_GAP_INJECTION="0"
python -c "...同上一行..."
# 期望：False
$env:CLOUDAGENT_GAP_INJECTION="maybe"
python -c "..."
# 期望：True（认不出 → 回退默认 on，不猜）

# ④ 全量无回归
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
# 期望：835 passed / 24 skipped（P1 之后）→ 本包只增不减

# ⑤ lint
python -m ruff check cloudagent_ext/diagnosis/switches.py cloudagent_ext/tool_system/tools/agent.py
```

## 4. 明确不做

| 不做 | 理由 |
|---|---|
| 改 `evaluation/runner.py` 的泄漏守卫 | 该文件在新评测体系里会删除；守卫逻辑并入评测仓治理层 |
| 给每个开关造计数器（进 meta） | 那是观测需求，改执行器契约要单独评审 |
| 改任何开关的**默认值** | 默认值即生产行为，动了就是行为变更 |
| 把 `token_budget.py` / `context_collapse` 的决策类并进来 | 总纲 §4.1 已收窄范围并标"暂缓" |
| 假守卫（只断言函数返回值的用例） | 见 T2a.3 的判据：改坏读取逻辑必须能红 |

## 5. 风险

| 风险 | 缓解 |
|---|---|
| `gap_injection_enabled` 语义变更影响既有行为 | 这是**修 bug**：之前写 `=false` 的人以为关了、其实在注入。handoff 单列，且用例覆盖 `false/0/no` 三种写法 |
| 守卫用例过度依赖私有函数（如直接调 `_with_current_state`） | 优先走公开入口；确实要调私有函数时在 docstring 写明"守的就是这个入口唯一性" |
| `goal_stop_strategy` 的离线守卫被误当成完整覆盖 | 在测试名与 handoff 里显式标 `[strategy-layer-only]` |
