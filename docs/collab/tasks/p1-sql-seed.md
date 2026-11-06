# P1 任务卡：sql 域取证基线

| 项 | 值 |
|---|---|
| 工作包 | P1 |
| 状态 | `in_progress`（2026-11-07 由 ZCode 认领） |
| 负责人 | ZCode |
| 分支 | `feat/p1-sql-seed` |
| 规格 | [`../design/p1-sql-seed.md`](../design/p1-sql-seed.md) |
| 预估 | 半天 |

## 写入范围

```
tests/fixtures/sql/seed.sql                                （新增）
tests/diagnosis/test_sql_seed_contract.py                  （新增）
tests/diagnosis/test_case_meta.py                          （改锁死数字）
cloudagent_ext/diagnosis/cases/sql/sql-0{01..09}.json       （改 verification/verified_against）
cloudagent_ext/diagnosis/cases/sql/sql-01{3,4}.json         （改 verification/verified_against）
docs/collab/handoffs/p1-sql-seed.md                        （新增）
```

**不许动**：`cloudagent_ext/diagnosis/case_audit.py`、`case_library.py`、
`tests/fixtures/sql/sync_seed_*.sql`、`sql-010/011/012.json`、任何 live 评测配置。

## 验收命令（全绿才算完成，逐条贴结果到 handoff）

```powershell
python -m pytest tests/diagnosis/test_sql_seed_contract.py -q
python -m pytest tests/diagnosis/test_case_meta.py -q
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider
python -m cloudagent_ext.diagnosis.case_audit
# 需要 PG 的两条：
$env:CLOUDAGENT_DB_DSN = (读 ~/.cloudagent/db_sim.env 里的同名变量)
python -m pytest tests/diagnosis/test_case_library.py -k GtReverification -q -rs
# 期望 1 passed（不是 skipped）
python -m ruff check tests/diagnosis/test_sql_seed_contract.py tests/diagnosis/test_case_meta.py
```

## 完成定义

- [ ] `tests/fixtures/sql/seed.sql` 连跑两次都成功（幂等，在临时库上验）
- [ ] seed 建出的库上，11 题的 `plan_contains` / `index_*` 断言逐条成立（贴 EXPLAIN 输出片段）
- [ ] 11 道题的 `verification` 已改 `static`，`verified_against` 都指向 seed 文件
- [ ] `test_case_meta.py` 的 28/4/6 已同步，`test_static_set_is_exact` 集合已含 11 个新 id
- [ ] 新增的静态守门测试覆盖规格 §3-T1.4 的三类检查，且**在没有任何 DSN 的环境下也能跑**
- [ ] `case_audit` 输出 `现在就能复核 28`
- [ ] handoff 里写了：取舍、被否方案、**没做的事**、规格疑问

## 特别提醒

- 规格 §6 第一条风险是**真实**的：`created_at` 改成固定基准后，
  sql-002 的"近 1 天"可能没有行 → 计划不再 `Seq Scan`。**必须真库验**。
- 磁盘上有旧 seed 可参考：`C:\Users\Administrator\Desktop\cloudAgent\scripts\sql_db\seed.sql`
  （**只读参考，不许 `cp` 过来当成品**——它有三处与本案不符，见规格 §3-T1.1 的表）。
