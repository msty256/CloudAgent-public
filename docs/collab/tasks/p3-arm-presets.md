# P3 任务卡：多臂预设与开关独立

| 项 | 值 |
|---|---|
| 工作包 | P3 |
| 状态 | `blocked`（等 P2 合并） |
| 负责人 | ZCode |
| 分支 | `feat/p3-arm-presets` |
| 规格 | [`../design/p3-arm-presets.md`](../design/p3-arm-presets.md) |
| 预估 | 一天 |

## 写入范围

```
cloudagent_ext/diagnosis/evaluation/runner.py             （--set / --arm-from / arm_derivation / 依赖校验）
tests/diagnosis/test_arm_presets.py                       （新增）
tests/diagnosis/test_evaluation_runner.py                 （只许新增用例）
docs/collab/handoffs/p3-arm-presets.md                    （新增）
```

**不许动**：`_BASELINE_ENV` 取值、任何既有 preset 的键值、`_compare_runs` 的表格口径、
`tests/diagnosis/test_ab_experiment.py` 的既有期望值。

## 验收命令

```powershell
python -m pytest tests/diagnosis/test_arm_presets.py -q
python -m pytest tests/diagnosis/test_ab_experiment.py tests/diagnosis/test_evaluation_runner.py -q
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync --variant arm:reduce
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync --variant baseline --set CLOUDAGENT_CONTEXT_REDUCE=on
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
```

## 完成定义

- [ ] `--set K=V` / `--arm-from NAME` 可用，语义按规格 §3-T3.1 三条定义
- [ ] `run_payload["arm_derivation"]` 含 `base` / `overrides` / `changed` / `single_variable` / `declared_dependencies`
- [ ] 每个 `arm:*`（除 `arm:inval`）相对 `baseline` 的 `single_variable == True`，且有用例守
- [ ] `arm:inval` 的单变量例外**在测试里逐字列名**（锁死，新增例外必须改测试）
- [ ] 依赖未满足时 `EvaluationError` 点名具体开关
- [ ] 所有验收命令离线可跑，**一次 live 都不许跑**
