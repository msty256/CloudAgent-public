# P2 实施规格：开关泄漏守卫泛化

> 状态：`approved` · 设计：DSH Lead（2026-11-07）· 实现：ZCode
> 任务卡：[`../tasks/p2-switch-guard.md`](../tasks/p2-switch-guard.md)
> 前置：P1 合并后开工（避免同时对 `tests/diagnosis` 大范围改动）

---

## 1. 问题陈述

`docs/diagnosis-redesign.md` §5.2 的阶段 5 提案里有一句结论：

> **前置已就绪**（阶段 3/4 开关 + 守卫用例）；多臂预设与跑批待做

**这句话目前只对一半。** 现状是：

| 开关 | 有没有"关了真关了"的守卫 |
|---|---|
| `CLOUDAGENT_GAP_INJECTION` | ✅ 有：`runner.py:527-530` 在 `gaps-off` 臂上 `injected_dispatches > 0` 时直接 `raise EvaluationError` |
| `CLOUDAGENT_CONTEXT_REDUCE` | ⚠️ 只有语义用例（`test_switches.py` 断言 `context_reduce_enabled()` 返回 False），**没有"关掉后行为真的不产生"的守卫** |
| `CLOUDAGENT_EVIDENCE_INVALIDATION` | ⚠️ 同上 |
| `CLOUDAGENT_DOMAIN_GATE` | ❌ 连语义用例都没有集中守卫（档位解析在 `runtime_session.domain_gate_mode()`，非法值告警回退） |
| `CLOUDAGENT_GOAL_STOP_STRATEGY` | ❌ 无守卫 |
| `CLOUDAGENT_KB_ENABLED` | ❌ 无守卫（`kb-on`/`kb-off` 两臂已经在 preset 里了） |

**为什么这是问题**（`switches.py` 的模块 docstring 自己写了）：

> 第 2 条最容易被破坏：开关加在三个地方，其中一处忘了判断，
> "关了"只是半关，对照结果就是脏的——而且从数据上完全看不出来。

也就是说：**现在能跑 `arm:reduce` 和 `arm:inval`，但跑出来的数据不能证明机制被关掉了。**
这正好是"统计效果不能宣称"的技术原因之一。

## 2. 现有实现的三个具体缺陷

### 缺陷 1：`gap_injection_enabled()` 绕过了 `switches.py` 的唯一入口

```python
# cloudagent_ext/tool_system/tools/agent.py:175-182
def gap_injection_enabled() -> bool:
    return os.environ.get("CLOUDAGENT_GAP_INJECTION", "on").strip().lower() != "off"
```

它自己读环境变量，**不走 `switches.env_flag()`**。后果有两个：

- 语义与 `env_flag` 不一致：`env_flag` 认 `{"1","true","yes","on","y","t"}` 八种真值、
  `{"0","false","no","off","n","f"}` 八种假值，认不出就回退默认；
  而这个函数只把**字面量 `"off"`** 当关，写 `CLOUDAGENT_GAP_INJECTION=false` 会**继续注入**。
- `switches.py` 的 `__all__` 里没有这个开关，等于它不在"开关登记表"上——
  新增开关时漏掉它就没人发现。

### 缺陷 2：`CLOUDAGENT_GOAL_STOP_STRATEGY` / `CLOUDAGENT_DOMAIN_GATE` 是"多值档位"，
但和布尔开关共用同一个"能不能关"的心智模型

`domain_gate_mode()` 有 `off` / `same_target` / `strict` 三档，`off` 是合法值。
`_BASELINE_ENV` 里 `CLOUDAGENT_DOMAIN_GATE: "off"`——**这就是臂的"关"**。
但没有任何东西验证"档位是 off 时，域闸真的没有拦任何派发"。

### 缺陷 3：守卫只在 `runner.py` 里，且只对 live 运行有意义

`runner.py:527` 的守卫要求 `experiment.injected_dispatches_max > 0` 才触发——
离线模式下这个数恒为 0，**守卫永远不触发，等于没守**。
（这不是 bug，是"离线跑不了这条守卫"的客观限制，但**离线可以守别的**：
装配层面"开关关了 → 工具表里没有那个工具 / 提示词里没有那一段"。）

## 3. 要做什么（四个 T）

### T2.1 建"开关登记表"，把散落的读法收敛到一处

在 `cloudagent_ext/diagnosis/switches.py` 里扩成登记表（**保持现有公开函数不变**，
新增结构，避免破坏现有 21 个用例）：

```python
@dataclass(frozen=True)
class SwitchSpec:
    env: str                  # 环境变量名
    kind: str                 # "bool" | "mode"
    default: Any              # bool 或 str
    modes: frozenset[str] = frozenset()   # kind=="mode" 时的合法值
    off_value: Any = None     # "关"的取值：bool 为 False，mode 为 "off"
    #: 关掉后**应当消失**的可观察行为（人话，用于守卫用例的参数化名称）
    off_effect: str = ""

SWITCHES: dict[str, SwitchSpec] = {...}
```

登记 5 个开关（`gap_injection` / `context_reduce` / `evidence_invalidation` /
`domain_gate` / `goal_stop_strategy`），并新增：

```python
def is_off(name: str) -> bool: ...     # 当前是否处于"关"
def current(name: str) -> Any: ...     # 当前生效值（bool 或 str）
```

**`gap_injection_enabled()` 必须改成走登记表**（保留函数名与签名，
`cloudagent_ext/tool_system/tools/agent.py` 里的调用点不动）。
⚠️ 这会**改变它的语义**（`false`/`no`/`0` 现在也算关）。这是**有意的修复**，
必须在 handoff 里单列，并在用例里明确断言旧行为是错的。

### T2.2 离线可跑的"装配层"守卫

新增 `tests/diagnosis/test_switch_guards.py`，**参数化遍历登记表**，每个开关至少两条：

1. **`off ⇒ 行为消失`**（机制层，离线可跑）：
   - `context_reduce`：构造一段取证大结果，跑 `CompressionPipeline`，
     开→有压缩统计；关→`compaction_stats` 为空 / 内容原样。**必须断言"确实不一样"**，
     不能只断言开关函数返回值。
   - `evidence_invalidation`：构造 `conflict` 关系，跑 `propagate_invalidation`，
     开→resolved 退回 open；关→缺口状态不变。
   - `gap_injection`：调 `_with_open_gaps()`，开→提示词含缺口段；关→不含。
     （**这条现在可能已经是个隐藏 bug**：如果 `_with_open_gaps` 内部没判开关，
     只是调用方判了，那直接调它会发现泄漏。实现时先查证，如果确实如此，
     修法是"在 `_with_open_gaps` 内部也判"，或明确写"入口唯一"并在守卫里走调用方。）
   - `domain_gate`（mode）：`off` 档下 `runtime.domain_gate()` 对"同目标 blocked"返回 None；
     `same_target` 档下返回停判。
   - `goal_stop_strategy`（mode）：`agent_report` 档下核查器不跑；`hybrid` 档下跑。
     （若这条需要 live，则**降级为"只守档位解析 + 装配标记"并在 handoff 里说明**。）

2. **`default ⇒ 生产行为不变`**：不设环境变量时，`current(name)` 等于 `default`，
   且**关键路径行为与未引入开关前一致**（用现有的等价性用例兜住，不重复造）。

### T2.3 把 `runner.py` 的泄漏守卫参数化

把 `runner.py:520-530` 那段"只守 gaps-off"的逻辑，改成读登记表：

```python
for name, spec in SWITCHES.items():
    if is_off(name) and _arm_leak_probe(name, run_payload) > 0:
        raise EvaluationError(f"开关泄漏：{name} 声明关闭，但 {spec.off_effect} 仍发生")
```

`_arm_leak_probe` 目前只有 `gap_injection` 有真实探针（`injected_dispatches`）。
其余四个**没有对应计数器**——所以这一步的正确做法是：

- 建一个 `_LEAK_PROBES: dict[str, callable]`，**只登记有探针的**；
- 对没有探针的开关，**不假装守住了**，而是让 `runner` 在 run 报告里写
  `"switch_guards": {"context_reduce": "no_probe", ...}`，
  并在 `_compare_runs` 的输出里**打一行警告**："该臂的 X 开关无泄漏探针，效果不可归因"。

> **设计取舍（重要）**：宁可在报告里显式写"这条守不住"，也不要写一个永远不触发、
> 看起来"已经守住了"的假守卫。后者比没有更危险。

### T2.4 更新 `docs/collab` 与总纲口径

- 在 `docs/collab/README.md` 的已完成项里记一行；
- 在 handoff 里明确写：**P2 完成后，`arm:reduce` / `arm:inval` / `arm:domain` 才第一次
  具备"可自证关闭"的条件**；没有探针的开关仍不可用于结论。

## 4. 验收标准

```powershell
# ① 登记表语义（扩展现有 21 例，保持全绿）
python -m pytest tests/diagnosis/test_switches.py -q

# ② 新增守卫
python -m pytest tests/diagnosis/test_switch_guards.py -q

# ③ 行为兼容：gap_injection 语义变更后，原有用例必须仍然说得通
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
# 基线 828 passed / 24 skipped；本包只会增加，不会减少

# ④ runner 参数化后离线报告不炸
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync --variant baseline
# 期望：正常产出，且 run json 里有 switch_guards 字段

# ⑤ 纯离线：不设任何 CLOUDAGENT_* 时，所有守卫用例都要能跑（不许 skip）
```

## 5. 明确不做

| 不做 | 理由 |
|---|---|
| 给每个开关造真计数器（如"压缩节省了多少 token"） | 那是观测需求，不是守卫需求；计数器要进 meta 就得改执行器契约，属独立工作包 |
| 改 `_BASELINE_ENV` 的取值 | 基线定义已被历史实验引用，动它会作废之前的 run |
| 把 `token_budget.py` / `context_collapse` 的决策类并进来 | 总纲 §4.1 已收窄范围并标"暂缓" |
| 强行给 `goal_stop_strategy` 造离线守卫 | 核查器需要模型；离线只能守档位解析。**写清楚，不假装** |

## 6. 风险

| 风险 | 缓解 |
|---|---|
| 改 `gap_injection_enabled()` 语义会改变现有 live 行为（有人配了 `=false` 以为关了、实际在注入） | 这是**修 bug**，handoff 单列；且 `switches.env_flag` 认不出就回退默认，不会把"maybe"当关 |
| 参数化后 `runner` 的 `EvaluationError` 触发条件变宽，可能让历史 run 重跑失败 | 只在 `is_off()` 为真时触发；历史 run 已经落盘，不重跑就不受影响 |
| 守卫用例过度依赖内部实现（如直接调 `_with_open_gaps`） | 优先走公开入口；确实要调私有函数时，在用例 docstring 里写明"守的就是这个入口唯一性" |
