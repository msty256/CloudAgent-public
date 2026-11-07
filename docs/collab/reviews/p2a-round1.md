# P2a 审查结论：开关登记表 + 机制守卫

> 审查人：DSH Lead · 2026-11-07 · 分支 `feat/p2a-switch-registry`（已合并）

## 结论：`PASS`

本批次风险最高的包（改了 3 个产品文件的读取逻辑 + 新增 25 条守卫）。
规格红线要求"改坏读取逻辑，守卫必须红"——**我自己动手验了一遍**，不只信 handoff。

## 1. 破坏性自验（这是本卡最重要的验收）

### 自验 ①：把 `gap_injection_enabled()` 改成恒 `return True`

```
FAILED test_off_keeps_prompt_untouched[false]
FAILED test_off_keeps_prompt_untouched[0]
FAILED test_off_keeps_prompt_untouched[no]
FAILED test_off_keeps_prompt_untouched[off]
4 failed, 21 passed
```

### 自验 ②：把 `current()` 的 bool 分支改成恒 `True`

```
FAILED TestContextReduceBehavior::test_off_false_disables_reduction
FAILED TestEvidenceInvalidationBehavior::test_off_zero_keeps_resolved
2 failed, 23 passed
```

**两次都红在对应守卫上。还原后 25 passed，`git status` clean（确认还原干净）。**

→ 守卫是真的，不是"只断言开关返回值"的假守卫。

## 2. 真 bug 修复（我独立跑，不用它的数字）

```
CLOUDAGENT_GAP_INJECTION='false' -> False    ← 修前 True
CLOUDAGENT_GAP_INJECTION='0'     -> False
CLOUDAGENT_GAP_INJECTION='no'    -> False
CLOUDAGENT_GAP_INJECTION='off'   -> False
CLOUDAGENT_GAP_INJECTION='FALSE' -> False    ← 大小写不误判
CLOUDAGENT_GAP_INJECTION='Maybe' -> True     ← 认不出 → 回退默认，不猜
CLOUDAGENT_GAP_INJECTION=''      -> True     ← 空值 → 默认
```

**语义变更确认为修 bug**：`=false/0/no` 从"无效（继续注入）"变"关闭"。
修前这三种写法的人以为关了、实际在注入，**对照实验数据全废且无报错**。

## 3. 我认可的一个实现取舍

`current()` 对 mode 开关的非法值**静默**回退，告警保留在两个读取点
（`domain_gate_mode` / `assessor_strategy`）。理由：告警要带模块 logger 上下文，
放登记表里会让 `switches.py` 依赖调用方日志配置。

规格 T2a.2 只要求"读取点从登记表取 env/合法值"，这个判断在范围内且更合理。

## 4. 诚实边界守住了

`goal_stop_strategy` 的守卫类名标 `[strategy-layer-only]`，handoff 明写
"核查器确实没被调用需要 live 才能验"。**没有假装守住执行层**——这是红线 4 的要求，
也是我最担心的"造假守卫"最容易发生的地方，它守住了。

## 5. 验收（我实跑）

| 命令 | 结果 |
|---|---|
| `test_switches.py`（既有 21 例） | **21 passed**（零改动，语义向后兼容） |
| `test_switch_guards.py`（新增） | **25 passed** |
| `tests/diagnosis` | **861 passed / 24 skipped**（836 + 25，只增不减） |
| `ruff check`（改动文件） | All checks passed |

## 6. 无遗留

评测侧（`evaluation/runner.py` 泄漏守卫参数化）已按范围变更加入新体系治理层，
不在本卡——`p1-p4-vs-eval-system.md` 已记录。
