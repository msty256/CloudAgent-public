# P1 实施规格：sql 域取证基线（11 题 `runtime → static`）

> 状态：`approved` · 设计：DSH Lead（2026-11-07）· 实现：ZCode
> 任务卡：[`../tasks/p1-sql-seed.md`](../tasks/p1-sql-seed.md)

---

## 1. 问题陈述（先纠正一个流行误解）

`docs/needs-quota.md` 第 4 节写着"卡在需要一个是可写的 PostgreSQL"，`docs/case-audit-2026-11-01.md`
P3 写着"本轮不做：需要真实 PostgreSQL"。**这两条在 2026-11-07 已经被证伪**：

- 本机 PG 16 服务在跑（`127.0.0.1:5433`），`superuser` 可写（我用 `BEGIN; CREATE INDEX ...; ROLLBACK;` 验过）；
- `cloudagent_sim` 里 **orders 50000 / customers 2000 / devices 50 / tenants 0** 已经在；
- 14 道 sql 题里，**11 道的断言我逐条跑通了**（见 `../baseline-2026-11-07.md` §4）。

所以 P1 不是"造数据"，是**把已经存在于某台机器上的数据，变成仓库内可复现、可断言的东西**。
这个区别很重要：前者是环境工程，后者才是代码交付。

## 2. 真正的缺口（三条，都不是"没数据"）

### 缺口 A：seed 脚本不在这个仓库里

`tests/fixtures/sql/` 只有 `sync_seed_primary.sql` / `sync_seed_secondary.sql`，
而 `sync_seed_primary.sql:13-19` 自己写着："本文件原本写「orders / customers 由既有 seed.sql 提供」，
但仓库内并不存在那个 seed.sql"。

我找到了那个文件：它在**同机另一个仓库** `C:\Users\Administrator\Desktop\cloudAgent\scripts\sql_db\seed.sql`
（2033 字节，2026-10-13）。内容正是 orders/customers 的生成逻辑 + `idx_customers_region` 索引。
**这个仓库是 `CloudAgent`（私有/旧），当前仓库是 `CloudAgent-public`。** 迁移时漏了。

→ **本工作包第一条交付：把该 seed（及其幂等约定）搬进本仓。**

### 缺口 B：`verification` 字段与实际状态脱节

11 道题的断言全部成立，但 `ground_truth.verification` 仍是 `runtime`。
`tests/diagnosis/test_case_meta.py` 把分布锁死在 `17 static / 15 runtime / 6 external`，
所以这 11 题不升级，分母就一直是 17。这不是文档问题，是**指标口径问题**。

### 缺口 C：断言没有 CI 可执行的守门

`tests/diagnosis/test_case_library.py::TestGtReverification` 已经会拿 `CLOUDAGENT_DB_DSN`
逐题复验 `plan_contains` / `index_absent` / `index_present`——**但 DSN 没配时整个类 skip**。
（我配上 DSN 跑过：`1 passed`。）也就是说：在有库的机器上它守得住，在没库的机器上它一声不响。

→ 这是可接受的现状（CI 没有 PG），但**必须让"跳过"这件事可见**：
本地基线文档要写清"配了 DSN 才有 14 题复验覆盖"，且 P1 要新增一个**不依赖 PG** 的静态守门。

## 3. 要做什么（四个 T）

### T1.1 迁移 seed 到本仓

新建 `tests/fixtures/sql/seed.sql`，内容 = 旧仓 `scripts/sql_db/seed.sql` 的逻辑 + 本仓现状的修正：

| 项 | 旧 seed | 本仓要求 |
|---|---|---|
| `customers` | 2000 行，region 四值循环 | 保持；注意本仓现状是 `north` 恰好 500 行，`i % 4` 生成的是 500/500/500/500，一致 |
| `orders` | 50000 行，`tenant_id = 1 + (i % 50)` | **必改**：`1 + (i % 50)` 产生 1..50 但 50 号只出现 1000 次、`i%50==0` 映射到 50，实际每个租户 1000 行——**与本仓现状一致，可保留**。但注释必须写明"每租户恰好 1000 行"这个**被断言依赖的事实** |
| `orders.created_at` | `now() - (i % 43200) minutes`（近 30 天滚动） | **必改**：滚动时间会让 sql-002 的"近 1 天"断言随执行时刻漂移。改为**固定基准时间** `2026-10-14 00:00:00+08` 往前推，保证 `created_at` 分布可复现 |
| `orders.status` | 四值循环 | 保持；注释写明"每状态 12500 行"（sql-008 的断言依赖选择性约 25%） |
| 索引 | `idx_customers_region` 唯一二级索引 | 保持，并**显式加注释**："orders 故意只有主键——sql-001/002/006/008/009 的 `index_absent` 断言依赖它" |
| `order_no` | 旧 seed 无此列 | 保留 `sync_seed_primary.sql:48` 那段 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS order_no` + 回填（sql-007/003 的语义用例用到业务单号） |
| 幂等 | `TRUNCATE orders, customers` 后重灌 | 保持。**注意 TRUNCATE 顺序**：`orders` 有 `REFERENCES customers(id)`，必须先 truncate orders；保持旧文件写法 |
| 授权 | `GRANT SELECT ... TO cloudagent_ro` | 保持；**不要**在本文件里写密码 |

**明确不做**：不新建 `tenants` / `devices` 的数据（那是 `sync_seed_primary.sql` 的职责，
两份 seed 不要重叠，否则谁覆盖谁说不清）。

### T1.2 把 11 题升级为 `static`

改 `cloudagent_ext/diagnosis/cases/sql/*.json` 的 `ground_truth`：

- `verification`: `runtime` → `static`
- `verified_against`: 必须写**可复核的依据**，格式统一为
  `tests/fixtures/sql/seed.sql + 2026-11-07 EXPLAIN 实测：<关键片段>`

具体 11 题（`sql-010/011/012` 不改，理由见 §5）：

| 题 | 新的 `verified_against` 要点 |
|---|---|
| sql-001 | `EXPLAIN SELECT * FROM orders WHERE tenant_id=7` → `Seq Scan on orders`；`pg_indexes` 无 tenant_id 索引 |
| sql-002 | 同上 but `created_at > now() - 1 day` → `Seq Scan on orders` |
| sql-003 | `Bitmap Index Scan on idx_customers_region` |
| sql-004 | `Filter: (lower(region)` 且 `idx_customers_region` 存在 |
| sql-005 | `Index Scan using orders_pkey` |
| sql-006 | `Hash Join` + orders.customer_id 无索引 |
| sql-007 | `Sort Key: amount DESC` |
| sql-008 | `Seq Scan on orders` + orders.status 无索引（选择性 25%） |
| sql-009 | `date(created_at)` 出现在 Filter + created_at 无索引 |
| sql-013 | `get_lock_info` 实测 `waiting: []`（当前无锁等待） |
| sql-014 | `get_table_stats(customers)` 实测 `n_live_tup=2000`、`region.n_distinct=4.0` |

### T1.3 更新锁死的分布数字（强制）

`tests/diagnosis/test_case_meta.py`：

```
EXPECTED_STATIC = 17 → 28
EXPECTED_RUNTIME = 15 → 4      （sql-010/011/012 + sync-001）
EXPECTED_EXTERNAL = 6（不变）
EXPECTED_TOTAL = 38（不变）
```

`test_static_set_is_exact` 的集合要加这 11 个 id。

**这不是"改测试让它变绿"**——它是本工作包的**验收点**：数字变了，说明口径真的改了；
如果谁只是把 case 改了却忘了改这里，测试会红，这正是设计意图。

### T1.4 新增不依赖 PG 的静态守门

新建 `tests/diagnosis/test_sql_seed_contract.py`，**只读文件、不连库**，守三件事：

1. `tests/fixtures/sql/seed.sql` 存在且包含四条被断言依赖的**显式事实**：
   - 不含 `CREATE INDEX` 作用于 `orders` 的 tenant_id / created_at / customer_id / status
     （用正则扫 `CREATE INDEX` 行，断言这四个列名不出现）；
   - 含 `idx_customers_region` 的创建；
   - 含 `ANALYZE`（否则 `n_distinct` 断言不稳）；
   - 不含明文密码 / DSN（正则 `postgresql://` 与 `PASSWORD`）。
2. 每道 `static` 的 sql 题，其 `verified_against` **必须提到 seed 文件路径**，否则红。
3. 幂等性：文件里 `TRUNCATE` 的每一张表，都必须在本文件里有对应的 `CREATE TABLE IF NOT EXISTS`。

> 为什么第 3 条重要：旧的 `sync_seed_primary.sql` 就是"假设别人会建表"，
> 结果那个"别人"不存在。**这条守门就是防止同样的坑再踩一次。**

## 4. 验收标准（逐条可执行）

```powershell
# ① 静态守门（不需要 PG）
python -m pytest tests/diagnosis/test_sql_seed_contract.py -q

# ② 分布数字已更新
python -m pytest tests/diagnosis/test_case_meta.py -q

# ③ 诊断域全绿（基线 828 passed / 24 skipped，本包应变成 828+新增）
python -m pytest tests/diagnosis -q --no-header -p no:cacheprovider

# ④ 有库机器上的真复验（必跑，且必须不是 skip）
$env:CLOUDAGENT_DB_DSN = "<从 ~/.cloudagent/db_sim.env 读>"
python -m pytest tests/diagnosis/test_case_library.py -k GtReverification -q -rs
# 期望：1 passed，不是 skipped

# ⑤ seed 可重放（在临时库或事务里验，不许污染 cloudagent_sim）
psql ... -f tests/fixtures/sql/seed.sql   # 连跑两次都必须成功
python -m pytest tests/diagnosis -q       # 跑完再验一次，断言仍成立

# ⑥ 体检工具输出
python -m cloudagent_ext.diagnosis.case_audit
# 期望：现在就能复核 28 / 需运行期环境 4 / 无法复核 6
```

## 5. 明确不做（写在这里防止越界）

| 不做 | 理由 |
|---|---|
| 升级 `sql-010`/`011`/`012` | 它们不是数据问题：010 是"历史锁等待"的工具能力边界，011 需要"DSN 不可达"环境，012 是协议行为。改成 `static` 是**撒谎** |
| 升级 `sync-001` | 需要下游 orders 表存在但为空（现在下游 orders **存在且为 0 行**，其实满足——但该题还依赖"下游表不存在"分支的语义决策，属另一个工作包） |
| pipeline 里跑 seed | seed 只在本地/CI 准备阶段跑；`--mode offline` 不许连库 |
| 改 `case_audit.py` 的口径 | `measurable_now = static`，这个口径是对的，只更新数字 |
| 动 `sync_seed_*.sql` | 它们服务 sync 域，改动会连带 sync-002~005 四道题 |

## 6. 已知风险

| 风险 | 缓解 |
|---|---|
| seed 的 `created_at` 改固定基准后，sql-002 的"近 1 天"可能变成 0 行，计划退化成 `Result` 而不是 `Seq Scan` | **这是真实风险**。seed 里必须让固定基准落在"最近 1 天内仍有足够行"的位置，或者把 sql-002 的查询改成相对 seed 基准的相对写法。**实现时必须在真库上跑 EXPLAIN 确认**，不能只看 SQL 写得对 |
| `TRUNCATE` 会清掉本机正在用的数据 | 只在 `cloudagent_sim` 上跑；**先在自己建的临时库验一遍幂等**（验收 ⑤） |
| 有人把 DSN 复制进仓库 | 静态守门 1 的第四项就是查这个 |
