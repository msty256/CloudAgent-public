# P1 审查结论 · 第一轮（部分审查，非终审）

> 审查人：DSH Lead · 时间：2026-11-07 04:14 · 分支：`feat/p1-sql-seed`
> 审查范围：T1.1（seed.sql）/ T1.2（11 题升级）/ T1.3（锁死数字）/ T1.4（静态守门）
> **未审**：T1.1 的两处缺陷修复、handoff（ZCode 尚未提交）

## 结论：`CHANGES_REQUESTED`

主体质量好，四项都已落地并跑通。**但 2 个真缺陷必须修**，其中 1 个是我在规格里
写错了方向、由实现暴露出来的。

> **行号已核对**：缺陷 1 在 `seed.sql:90-91`，缺陷 2 在 `seed.sql:58`
> （声明与行为不一致的那句在 `:36-37`）。

---

## ✅ 已通过（我实测复验，不是只看声明）

| 验收项 | 我的验证方式 | 结果 |
|---|---|---|
| `tests/diagnosis` 全量 | 实跑 | **835 passed / 24 skipped**（基线 828，+7） |
| `test_sql_seed_contract.py` + `test_case_meta.py` | 实跑 | 19 passed |
| `case_audit` 分布 | 实跑 | **28 / 4 / 6**，与规格一致 |
| `ruff check` 两个新/改文件 | 实跑 | All checks passed |
| `seed.sql` 幂等（连跑两次） | **独立库 `p1_seed_probe` 实跑** | exit 0，重放 **0.58 秒** |
| seed 分布（50000/2000、租户各 1000、状态各 12500、region 各 500） | 独立库查询 | 全部吻合 |
| 外键完整性（customer_id → customers） | 独立库查询 | 0 空、0 越界、0 孤儿 |
| 索引清单（orders 无二级索引） | 独立库查询 | 正确 |
| sql-001..009 的 `plan_contains` | 独立库逐条 EXPLAIN | **全部命中** |
| `TestGtReverification` 跑在 seed 产出的库上 | `CLOUDAGENT_DB_DSN` 指向 `p1_seed_probe` | **1 passed（非 skip）** |

**特别肯定**：`verified_against` 写的是**依据**而不是"实测通过"。sql-002 那条尤其好：

> `seed 固定基准 2026-10-14，估算 rows=5 仍全表扫描（created_at 无索引，预估计划不做常量折叠；实际命中 0 行不影响计划形状）`

这句直接把我 §6.1 的更正讲清楚了，比我写的规格还准。

---

## ❌ 缺陷 1（必改）：`GRANT ... ALL TABLES` 授权过宽，且**连带默认权限**

**位置**：`tests/fixtures/sql/seed.sql:90`

```sql
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cloudagent_ro;
```

**问题（我实测确认）**：同一台机器上 `sync_seed_primary.sql` 会建 `tenants` / `devices`。
本文件跑一次，这些表也会被授权——但文件头 `:36-37` 声称"分工边界：tenants / devices 归
sync_seed_primary.sql，两份 seed 不重叠"。**声明与行为不一致。**

**比规格里写的更严重**：我在 `p1_def2` 里建了个 `tenants` 表验证，发现不只已存在的表被授权，
**默认权限也被写了**：

```
pg_default_acl: postgres | public | r | {cloudagent_ro=r/postgres}
```

也就是说**今后任何人在 `public` 里建的表都会自动对只读角色可读**。
这比"多授了两张表"严重得多——它是一条永久的、看不见的授权。

**修法**（按推荐顺序）：

```sql
-- 1) 只授自己建的表
GRANT SELECT ON customers, orders TO cloudagent_ro;

-- 2) 删掉 ALTER DEFAULT PRIVILEGES 那行——它不在本 seed 的职责里
--    （若确需默认权限，应由 sync seed 或 bootstrap 脚本负责，并在该文件里说明）
```

`GRANT USAGE ON SCHEMA public` 可以保留（没有它 `GRANT SELECT` 不生效）。

---

## ❌ 缺陷 2（必改）：`TRUNCATE` 在有第三方 FK 时失败，且报错**指不出是 seed 的问题**

**位置**：`tests/fixtures/sql/seed.sql:58`

**实测复现**（`p1_def2` 库）：

```sql
CREATE TABLE audit_log (id bigint, order_id bigint REFERENCES orders(id));
-- 然后重放 seed：
psql:seed.sql:58: 错误: 在一个外键约束中无法删除 (truncate) 一个表的关联
DETAIL:  表"audit_log" 引用"orders".
HINT: 同时截断表"audit_log" ,或者使用TRUNCATE ... CASCADE.
```

exit code **3**。**这是我初稿里判断"当前不会触发"的地方判错了**——
触发条件不是"表上有索引"，而是"有第三方 FK 引用 orders/customers"，
在真实的 `cloudagent_sim` 上完全可能出现（sync 域的表就可能引用这些表）。

**修法二选一，我倾向 A**：

- **A（推荐）**：保留 `TRUNCATE orders, customers;`，**在注释里写明前提**：
  "本 seed 假定 orders/customers 上除彼此之外无其它 FK 依赖；若有，需先手工处理"。
  理由：`CASCADE` 会**静默清空别人的表**，在共享库上是危险默认。
  注释 + 保留失败，让人在失败时看到原因。
- B：改成 `TRUNCATE orders, customers CASCADE;` 并注明风险——**仅在确认目标库只用于本 seed 时可用**。

**不许**选"删掉 TRUNCATE 改 TRUNCATE 单表"之类的绕法，那会破坏幂等。

---

## ⚠️ 缺陷 3（建议改，不阻塞）：静态守门漏了我规格里的一条

规格 §3-T1.4 第 1 条我加过一条检查：

> **时间列的生成式不得出现 `now()` / `current_date` / `current_timestamp`**

`test_sql_seed_contract.py` 里**没有实现这条**。但这条恰恰是防 D2 那种回归的
（有人把固定基准改回 `now()`，分布就开始漂移，而其它断言全绿看不出来）。

实现时注意规格里已写的两条坑：
1. **先剥 `--` 行注释再扫**（`seed.sql` 的 D2 注释里故意写着 `now()`，直接扫会误报）；
2. `CREATE INDEX` 检查要**按行**匹配，别跨行。

参考实现：

```python
def _code_lines() -> list[str]:
    return [ln.split("--")[0] for ln in _seed_text().splitlines()]

def test_no_rolling_time_in_seed(self) -> None:
    offenders = [
        ln.strip() for ln in _code_lines()
        if re.search(r"\b(now|current_date|current_timestamp)\s*\(", ln, re.IGNORECASE)
        or re.search(r"\bcurrent_date\b", ln, re.IGNORECASE)
    ]
    assert not offenders, "seed 的时间生成式不得用滚动时间（破坏可复现）：" + repr(offenders)
```

---

## 需要你补的东西

1. 修缺陷 1、2，缺陷 3 建议一起做；
2. 修完重跑：`test_sql_seed_contract.py` + `test_case_meta.py` + `tests/diagnosis` 全量；
3. 在一个**临时库**上验一次：`CREATE DATABASE p1_verify; psql -f seed.sql` 连跑两次
   （不要在我的 `cloudagent_sim` 上验，也不要用我留下的 `p1_seed_probe`——已删）；
4. 写 `docs/collab/handoffs/p1-sql-seed.md`，含：取舍、被否方案、
   **没做的事**、规格疑问（如果你觉得我上面哪条判错了，直接写进"规格疑问"反驳）。

## 我这边已清理

临时库 `p1_seed_probe` / `p1_def2` 都已 `DROP`，`cloudagent_sim` **未被改动**。
