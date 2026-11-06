> ⚠️ **本卡已作废（2026-11-07）**。新评测体系立项后，本卡目标文件属于待删除/待迁移范围。
> 实际执行范围请见 [P2a](../design/p2a-switch-registry.md) / [P1-P4 评估](../design/p1-p4-vs-eval-system.md)。
> 保留本文件仅为存档。

# P4 任务卡：评测链路缺陷收口

| 项 | 值 |
|---|---|
| 工作包 | P4 |
| 状态 | `ready` |
| 负责人 | ZCode |
| 分支 | `feat/p4-eval-chain` |
| 规格 | [`../design/p4-eval-chain.md`](../design/p4-eval-chain.md) |
| 预估 | 半天到一天 |
| 可与 P1 并行 | 是（文件不重叠） |

## 写入范围

```
tests/diagnosis/test_eval_bash_availability.py            （新增）
cloudagent_ext/diagnosis/evaluation/scoring.py            （截断判定）
cloudagent_ext/diagnosis/evaluation/executors.py          （Bash 显式拒绝）
cloudagent_ext/agent/registry.py                          （F821：加 Any 导入）
tests/diagnosis/test_session_wiring.py                    （F821：加 pathlib 导入）
docs/collab/handoffs/p4-eval-chain.md                     （新增）
```

**不许动**：`permissions/` 里的模式定义、`_RESTRICTED_PERMISSION_MODE` 的取值、
`dontAsk` → 任何更宽松模式的改动、provider/端点配置。

## 验收命令

```powershell
python -m pytest tests/diagnosis/test_eval_bash_availability.py -q -rs
python -m pytest tests/diagnosis/test_eval_metrics.py tests/diagnosis/test_evaluation_runner.py -q
python -m ruff check cloudagent_ext tests          # 期望 All checks passed
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync
```

## 完成定义

- [ ] 三条 Bash 用例全绿，其中**"拒绝必须是 `is_error=True`"是安全守门，不许妥协**
- [ ] 截断判定新增了结构化信号，且每条信号都配了反向用例（完整回答不许被误判）
- [ ] `unfinished` / `invalid_output` 的分界线写进了 `scoring.py` 模块 docstring
- [ ] `ruff check cloudagent_ext tests` 清零
- [ ] 如果 `executors.py:96-99` 的注释（"可证明只读且限域的命令放行"）与代码不符，
      **在 handoff 里单列**，不要偷偷改注释了事
- [ ] handoff 里写清：`dontAsk` 下 Bash 到底卡在哪一层（权限检查 / 沙箱 / cwd）

## 红线（违反直接打回）

1. 把 `_RESTRICTED_PERMISSION_MODE` 改成 `bypassPermissions` 或 `acceptEdits`
2. 只在测试里绕过权限上下文（用默认 `ToolContext` 测"通过"而生产仍是 `dontAsk`）
3. 用输出长度猜截断
