# P1 任务卡：sql 域取证基线

| 项 | 值 |
|---|---|
| 工作包 | P1 |
| 状态 | `done`（二审 PASS，2026-11-07 已合并） |
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
- [ ] **【新增】`seed.sql` 的授予范围收到自己建的表**：`GRANT SELECT ON customers, orders`
      而不是 `ALL TABLES IN SCHEMA public`（理由见规格 §3-T1.5 缺陷 1）
- [ ] **【新增】`seed.sql` 的 `TRUNCATE` 依赖前提写进注释**：声明"除 orders↔customers
      彼此之外无其它 FK 依赖；有则需先手工处理"，让失败信息与注释对得上（缺陷 2）
- [ ] seed 建出的库上，11 题的 `plan_contains` / `index_*` 断言逐条成立（贴 EXPLAIN 输出片段）
- [ ] 11 道题的 `verification` 已改 `static`，`verified_against` 都指向 seed 文件，
      **且写的是依据（索引缺失）不是"实测通过"**（模板见规格 §3-T1.2 末尾）
- [ ] `test_case_meta.py` 的 28/4/6 已同步，`test_static_set_is_exact` 集合已含 11 个新 id
- [ ] 新增的静态守门测试覆盖规格 §3-T1.4 的三类检查，且**在没有任何 DSN 的环境下也能跑**；
      注意 §3-T1.4 里那两条实现细节（剥注释再扫、`CREATE INDEX` 按行匹配）
- [ ] `case_audit` 输出 `现在就能复核 28`
- [ ] handoff 里写了：取舍、被否方案、**没做的事**、规格疑问

## 已由 Lead 在真库验收过的项（不用重做，直接用）

我在独立临时库 `p1_seed_probe` 上跑过你的初版 `seed.sql`，以下**已确认通过**，
你继续往下做即可，不必回头重验（细节见规格 §3-T1.5）：

- 首次执行、**第二次执行（幂等，0.58 秒）** 均成功；
- 行数与分布：orders 50000 / customers 2000；tenant_id 1..50 各 1000；
  status 四值各 12500；region 四值各 500；
- 外键完整性：0 空、0 越界、0 孤儿客户；
- 索引清单正确（orders 无二级索引）；
- sql-001..009 的全部 `plan_contains` 命中；
- `TestGtReverification` 在该 seed 库上 **1 passed（非 skip）**。

**只需修上面「完成定义」里标注【新增】的两条，然后进 T1.2。**

## 特别提醒

- ~~规格 §6 第一条风险是**真实**的：`created_at` 改成固定基准后，
  sql-002 的"近 1 天"可能没有行 → 计划不再 `Seq Scan`。**必须真库验**。~~
  **已作废**：该论断被实测推翻，且我已追测"老化 24 天后断言仍成立"。
  现结论见 `design/p1-sql-seed.md` §6.1 与 `baseline-2026-11-07.md` §4.1，
  **照那两份写，不要照这条旧提醒做设计**。
- 磁盘上有旧 seed 可参考：`C:\Users\Administrator\Desktop\cloudAgent\scripts\sql_db\seed.sql`
  （**只读参考，不许 `cp` 过来当成品**——它有三处与本案不符，见规格 §3-T1.1 的表）。
- `verified_against` 要写**依据**（"该列无索引 ⇒ 不选索引"），不是"实测通过"，
  也不是命中行数。模板与反例见规格 §3-T1.2 末尾。
