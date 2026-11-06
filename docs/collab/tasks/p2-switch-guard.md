# P2 任务卡：开关泄漏守卫泛化

| 项 | 值 |
|---|---|
| 工作包 | P2 |
| 状态 | `blocked`（等 P1 合并，避免同改 `tests/diagnosis`） |
| 负责人 | ZCode |
| 分支 | `feat/p2-switch-guard` |
| 规格 | [`../design/p2-switch-guard.md`](../design/p2-switch-guard.md) |
| 预估 | 一天 |

## 写入范围

```
cloudagent_ext/diagnosis/switches.py                      （开关登记表）
cloudagent_ext/tool_system/tools/agent.py                 （gap_injection_enabled 走登记表）
cloudagent_ext/diagnosis/evaluation/runner.py             （泄漏守卫参数化 + switch_guards 字段）
tests/diagnosis/test_switches.py                          （扩充，保留原 21 例语义）
tests/diagnosis/test_switch_guards.py                     （新增）
tests/diagnosis/test_evaluation_runner.py                 （若有断言旧字段则同步）
docs/collab/handoffs/p2-switch-guard.md                   （新增）
```

**不许动**：`_BASELINE_ENV` 的取值、`token_budget.py`、`context_collapse/`、
任何 live 运行产物。

## 验收命令

```powershell
python -m pytest tests/diagnosis/test_switches.py tests/diagnosis/test_switch_guards.py -q
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync --variant baseline
python -m ruff check cloudagent_ext/diagnosis/switches.py cloudagent_ext/tool_system/tools/agent.py
```

## 完成定义

- [ ] `SWITCHES` 登记表覆盖 5 个开关，每个都有 `off_effect` 描述
- [ ] 每个开关至少一条"关掉 ⇒ 行为消失"的用例，且**断言行为差异**不是断言开关返回值
- [ ] `gap_injection_enabled()` 语义变更（`false`/`no`/`0` 现在也算关）已在此用例中显式覆盖，
      并在 handoff 里单列"这是修 bug 不是回归"
- [ ] 没有探针的开关，在 run 报告里写 `"no_probe"`，并在 `_compare_runs` 输出里给警告
- [ ] 全部守卫用例**在没有任何 CLOUDAGENT_* 环境变量时也能跑**（不许 skip）
- [ ] handoff 明确写：P2 之后哪些臂第一次具备"可自证关闭"，哪些仍不可用于结论

## 特别提醒

- **不许造假守卫**：`_LEAK_PROBES` 里没有的开关，宁可在报告里写 `no_probe`，
  也不要写一个永不触发的检查。
- 离线模式下 `injected_dispatches` 恒为 0，所以 `gaps-off` 那条老守卫在离线**不会触发**——
  这是客观限制，不是你要修的 bug；但要在 handoff 里说清"哪条守卫只在 live 有效"。
