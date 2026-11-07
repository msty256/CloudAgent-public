# P2a 任务卡：开关登记表与机制守卫（产品侧）

| 项 | 值 |
|---|---|
| 工作包 | P2a |
| 状态 | `in_review`（完成待审；2026-11-07 ZCode） |
| 负责人 | ZCode |
| 分支 | `feat/p2a-switch-registry` |
| 规格 | [`../design/p2a-switch-registry.md`](../design/p2a-switch-registry.md) |
| 预估 | 半天 |
| 依赖 | 无（已从原 P2 的 `blocked` 解除） |

> **范围变更**：原 P2 的评测侧（`evaluation/runner.py` 泄漏守卫参数化）
> 已并入新评测体系，**不在本卡**。理由见
> [`../design/p1-p4-vs-eval-system.md`](../design/p1-p4-vs-eval-system.md)。

## 写入范围

```
cloudagent_ext/diagnosis/switches.py                  （开关登记表）
cloudagent_ext/tool_system/tools/agent.py             （gap_injection_enabled 走登记表）
cloudagent_ext/diagnosis/runtime_session.py           （domain_gate_mode 取登记表的 env/合法值）
cloudagent_ext/diagnosis/assessor.py                  （assessor_strategy 取登记表的 env/合法值）
tests/diagnosis/test_switches.py                      （扩，保留原 21 例语义）
tests/diagnosis/test_switch_guards.py                 （新增）
docs/collab/handoffs/p2a-switch-registry.md           （新增）
```

**不许动**：`cloudagent_ext/diagnosis/evaluation/**`（待删）、任何开关的**默认值**、
`token_budget.py`、`context_collapse/`、`_BASELINE_ENV`。

## 三件必做的事（详见规格）

1. **建 `SWITCHES` 登记表**（5 条，含 `off_effect` 人话描述）
2. **修 `gap_injection_enabled()`**：现在只认字面量 `"off"`，
   写 `=false` / `=0` / `=no` 会**静默继续注入**——对照实验数据全废且无报错
3. **每个开关一条"关掉 ⇒ 行为消失"的守卫**，参数化遍历登记表

## 验收命令

```powershell
# ① 既有 21 例语义用例必须原样全绿
python -m pytest tests/diagnosis/test_switches.py -q

# ② 新守卫
python -m pytest tests/diagnosis/test_switch_guards.py -q

# ③ 真 bug 修复验证（本包核心）
$env:CLOUDAGENT_GAP_INJECTION="false"
python -c "from cloudagent_ext.tool_system.tools.agent import gap_injection_enabled as f; print(f())"
# 期望 False（修前是 True）

$env:CLOUDAGENT_GAP_INJECTION="maybe"
python -c "..."
# 期望 True（认不出 → 回退默认，不猜）

# ④ 全量
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
# 期望 835 passed / 24 skipped，只增不减

# ⑤ lint
python -m ruff check cloudagent_ext/diagnosis/switches.py cloudagent_ext/tool_system/tools/agent.py
```

## 完成定义

- [ ] `SWITCHES` 覆盖 5 个开关，每条都有 `env/kind/default/off_value/off_effect`
- [ ] `gap_injection_enabled()` 走登记表；`=false` / `=0` / `=no` **确实关闭**（用例覆盖三种写法）
- [ ] 每个开关至少一条"关掉 ⇒ 行为消失"的守卫，且**断言行为差异**不是断言返回值
- [ ] 守卫用例在**没有任何 `CLOUDAGENT_*` 环境变量**时也能跑（不许 skip）
- [ ] **自验守卫有效**：把某开关的读取逻辑故意改坏，对应守卫必须红（本地验一次再改回，handoff 里写验过哪条）
- [ ] `goal_stop_strategy` 的守卫标记为 `[strategy-layer-only]`，handoff 说明离线只能守到策略层
- [ ] `tests/diagnosis` 全量绿；`ruff` 对改动文件绿
- [ ] handoff 写清：语义变更（`false/0/no` 从无效变关闭）是**修 bug** 而非回归

## 红线

1. **不许造假守卫**——只断言 `is_off()` 返回值的用例等于没守。
   判据：改坏读取逻辑后守卫必须红。
2. **不许改任何开关的默认值**——默认值即生产行为。
3. **不许动 `evaluation/**`**——那是待删代码。
4. `goal_stop_strategy` 离线只能守策略层，**不要假装守住了执行层**。
