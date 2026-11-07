# P2a 交接说明：开关登记表与机制守卫（产品侧）

> ZCode · 2026-11-07 · 分支 `feat/p2a-switch-registry`

## 改了什么

| 文件 | 改动 |
|---|---|
| `cloudagent_ext/diagnosis/switches.py` | 新增 `SwitchSpec` + `SWITCHES`（5 条登记，含 `off_effect` 人话描述）+ `current()` / `is_off()` 统一读取入口；模块 docstring 的"每加开关要加守卫"升级为可操作三步流程；既有 3 个公开函数与全部常量原样保留 |
| `cloudagent_ext/tool_system/tools/agent.py` | `gap_injection_enabled()` 改走登记表（`env_flag(SWITCHES["gap_injection"].env, True)`），**修真 bug**：修前只认字面量 `"off"` |
| `cloudagent_ext/diagnosis/runtime_session.py` | `domain_gate_mode()` 的 env 名/合法值/默认值改从 `SWITCHES["domain_gate"]` 取，**保留非法值 `logger.warning` + 回退默认** |
| `cloudagent_ext/diagnosis/assessor.py` | `assessor_strategy()` 同上，取自 `SWITCHES["goal_stop_strategy"]`，告警行为保留 |
| `tests/diagnosis/test_switch_guards.py`（新增） | 25 条：登记表形状守卫（3×5）+ 5 个开关各一条"关掉 ⇒ 行为消失"行为守卫 |

**没动的**：任何开关默认值、`token_budget.py`、`context_collapse/`、`_BASELINE_ENV`、
`evaluation/**`、`ENV_DOMAIN_GATE` / `STRATEGIES` 等既有常量（仍是模块级导出，向后兼容）。

## 真 bug 修复验证（本包核心）

```
CLOUDAGENT_GAP_INJECTION=false → False   （修前 True——对照实验数据全废且无报错）
CLOUDAGENT_GAP_INJECTION=0     → False
CLOUDAGENT_GAP_INJECTION=no    → False
CLOUDAGENT_GAP_INJECTION=off   → False
CLOUDAGENT_GAP_INJECTION=maybe → True    （认不出 → 回退默认 on，不猜）
```

**语义变更声明**：`=false` / `=0` / `=no` 从"无效（继续注入）"变成"关闭"。
这是**修 bug 而非回归**——修前这三种写法的人以为关了、实际在注入；
`runner.py` 的 preset 用 `"off"`，不受影响。

## 守卫是"真的"——改坏自验记录（本地验过再改回）

| 故意改坏 | 预期 | 实测 |
|---|---|---|
| `gap_injection_enabled()` 恒 `return True`（无视环境变量） | 注入守卫必须红 | **4 failed**（`test_off_keeps_prompt_untouched` 的 false/0/no/off 全部） |
| `domain_gate_mode()` 无视环境变量恒 `same_target` | 域闸守卫必须红 | **1 failed**（`test_off_allows`） |
| 还原后 | 全绿 | **25 passed** |

守卫断言的都是行为差异：注入段（`## 当前有效状态`）在提示词里出现与否、
`propagate_invalidation` 有没有退回 open、`CompressionPipeline` 的 `layers_applied`、
`domain_gate()` 返回 StopDecision 还是 None、`should_verify` 在 `agent_report` 档
是否永不核查——不是断言 `is_off()` 的返回值。

## 验收结果

| 命令 | 结果 |
|---|---|
| `pytest tests/diagnosis/test_switches.py -q` | **21 passed**（既有语义用例零改动） |
| `pytest tests/diagnosis/test_switch_guards.py -q` | **25 passed** |
| 真 bug 验证（上表） | 全部符合规格 ③ |
| `pytest tests/diagnosis -q` | **861 passed / 24 skipped**（836 基线 + 25，只增不减） |
| `pytest tests/tool_system -q` | **115 passed**（agent.py 无回归） |
| `ruff check`（5 个改动文件） | All checks passed |

## goal_stop_strategy 的诚实边界

`test_switch_guards.py` 对该开关只覆盖**策略层**（`assessor_strategy()` 解析正确 +
`should_verify` 在 `agent_report` 档返回 False），用例与类名都标了
`[strategy-layer-only]`。"独立核查器确实没被调用"需要 live 才能验，
本包不假装守住了执行层（规格 T2a.3 与红线 4 的要求）。

## 取舍与被否方案

- `current()` 对 mode 开关的非法值**静默**回退（告警保留在 `domain_gate_mode` /
  `assessor_strategy` 两个读取点）——告警带模块 logger 上下文，放登记表里会让
  `switches.py` 依赖调用方日志配置；规格 T2a.2 只要求读取点"从登记表取 env/合法值"。
- 未给 `context_reduce_enabled()` / `evidence_invalidation_enabled()` 改签名：
  它们已经语义正确，登记表只是补登记；改签名会让 diff 变大且无行为收益。
- 被否：让 `is_off()` 对 bool 开关直接调 `env_flag(spec.env, spec.default) == spec.off_value`、
  对 mode 走独立逻辑——统一走 `current()` 保证"当前生效值"只有一个定义。

## 没做的事

- 评测侧（`evaluation/runner.py` 泄漏守卫参数化）——已并入新评测体系治理层，不在本卡；
- 未给开关加计数器/进 meta（规格 §4 明确不做）；
- 未动任何 live 评测配置与默认值。
