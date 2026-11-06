# P1 审查结论 · 第二轮（终审）

> 审查人：DSH Lead · 2026-11-07 · 分支：`feat/p1-sql-seed`（HEAD `783cad1`）
> 上一轮：[`p1-round1.md`](./p1-round1.md)（`CHANGES_REQUESTED`）

## 结论：`PASS`（可合并）

round-1 的 3 条缺陷全部修复且可验收，未引入新的越界改动。

---

## 1. 缺陷修复复验（逐条实测，不是看声明）

| # | round-1 缺陷 | 修复内容 | 我的复验 |
|---|---|---|---|
| 1 | `GRANT ... ALL TABLES` 授权过宽 + 默认权限 | 收窄为 `GRANT SELECT ON customers, orders`；删除 `ALTER DEFAULT PRIVILEGES` | ✅ 扫 seed 代码行：只剩两条 GRANT（USAGE + 两表 SELECT），无 `ALTER DEFAULT PRIVILEGES` |
| 2 | `TRUNCATE` 遇第三方 FK 失败且报错指不出原因 | 注释写明前提"除 orders↔customers 彼此外无其它 FK；有则整体失败且刻意不 CASCADE" | ✅ 前提与 `TRUNCATE orders, customers;` 对应；与 ZCode 在临时库的实测一致 |
| 3 | 静态守门缺"时间生成式不得用滚动时间" | 新增 `test_no_rolling_time_in_seed`，剥 `--` 注释后扫 `now(`/`current_date`/`current_timestamp` | ✅ 8 条守门全过（20 passed 含 case_meta 12） |

## 2. 验收闸门（全部由我复跑）

| 闸门 | 结果 |
|---|---|
| `test_sql_seed_contract.py` + `test_case_meta.py` | **20 passed** |
| `cloudagent_ext.diagnosis.case_audit` | **28 / 4 / 6** ✅ 与规格一致 |
| `tests/diagnosis` 全量 | **836 passed / 24 skipped**（基线 828，+8 新增） |
| `tests/context` + `tests/tool_system` | **280 passed**（165 + 115，无回归） |
| `GtReverification`（配 `CLOUDAGENT_DB_DSN`） | **1 passed（非 skip）** |
| `ruff check` 两个改动文件 | **All checks passed** |
| seed 结构静态核对 | `TRUNCATE orders, customers;` 单条、无 orders 索引、无凭据 ✅ |

## 3. `verified_against` 质量抽验

11 题全部以 `tests/fixtures/sql/seed.sql` 开头 + 说明依据（索引缺失）。
**且没有会漂移的数值**（我扫了 `rows=\d+` / `估算 rows`，全部为空）——
这正是 round-1 之后我改口径的要点，ZCode 执行到位。

## 4. handoff 里 3 条规格疑问的裁决

| ZCode 疑问 | 裁决 |
|---|---|
| ① 顺手改了 `verified_at`（2026-11-01 → 11-07） | **同意保留**。static 的元数据日期与证据日期必须一致，属范围精神内 |
| ② 移除了 sql-002 的"估算 rows=5"、sql-008 的"rows=12415" | **同 ZCode 的判断**。会漂移的数值不该进 `verified_against`；"选择性 ~25%" 保留是对的（来自 seed 分布 F3/F4，稳定事实） |
| ③ 验收 ⑤ 用 cloudagent_sim 重放而非新建临时库 | **接受**。语义覆盖了（重放 + GtReverification + 全量），但见下方遗留问题 1 |

## 5. 遗留问题（不阻塞合并，已转成独立任务）

ZCode 在 handoff §6 主动报告了三个问题，态度是对的。我核实后确认：

1. 🔴 **`cloudagent_sim` 上留有 `pg_default_acl` 残留**
   实测确认：`postgres | public | r | {cloudagent_ro=r/postgres}` 仍在。
   这是 round-1 缺陷 1 的**历史残留**——修好的 seed 只约束今后执行，不清存量。
   影响：今后任何人在 `public` 建表，只读角色自动可读。
   → 转 **P0'**，单独任务（见 `tasks/p0-prime-acl-cleanup.md`）

   **但要澄清一点**（我初稿判断过宽）：`tenants` / `devices` 的**表级 SELECT 是产品必需的**
   （sync 域诊断要读这两张表），不能收。因此 P0' 只清 `pg_default_acl` 一条。

2. `tenants` / `devices` 未灌数 —— 属 sync seed 职责，**不在 P1 范围**，接受。
3. `sql-010/011/012` + `sync-001` 保持 runtime —— **判断正确**，这三题分别是
   工具能力边界 / 环境降级 / 协议行为，改成 static 是撒谎。

## 6. 合并建议

```
git checkout main
git merge --no-ff feat/p1-sql-seed
```

合并后 `main` 的案例分布从 17/15/6 变成 **28/4/6**，`case_audit` 会显示 74% 可复核。

⚠️ **合并前确认一件事**：本仓当前 `main` 上有我未提交的文档改动
（`docs/collab/**`）。合并前先处理，避免混入。

## 7. 移交清单

| 项 | 状态 |
|---|---|
| P1 分支 | ✅ 可合并 |
| P0'（清 pg_default_acl） | 📋 已出任务卡 |
| P4a（两行 F821） | 📋 已出任务卡 |
| P2a（开关登记表） | 📋 已出设计 + 任务卡 |
| P3 / P2b / P4 其余 | ❌ 作废或并入评测体系，见 `design/p1-p4-vs-eval-system.md` |
