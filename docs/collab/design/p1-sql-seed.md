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

**`verified_against` 的写法要求（重要，别写成"跑通了"）**：必须写出**断言的依据**，
不是"我跑了一下通过"。差别在于依据能被后人复核并判断何时失效。模板：

```
tests/fixtures/sql/seed.sql 定义 <表/列> 无索引；
2026-11-07 实测 EXPLAIN 命中 "<plan 片段>"（依据是索引缺失，非命中行数）
```

反例（会被打回）：
- `"实测通过"` / `"已核对"` —— 没有依据，别人无法复核；
- `"近 1 天命中 1440 行"` —— 这是数值断言，会随时间漂移（见 §6.1），**不是**本题的依据。

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
   - 不含明文密码 / DSN（正则 `postgresql://` 与 `PASSWORD`）；
   - **时间列的生成式不得出现 `now()` / `current_date` / `current_timestamp`**
     ——滚动时间会让同一份 seed 在不同日子产出不同分布，破坏可复现性（详见 §6.1）。

   ⚠️ **两条实现细节（我已在 ZCode 初版 `seed.sql` 上踩到，别重复）**：

   1. **必须先剥掉 SQL 行注释再扫**。`seed.sql` 的 D2 注释里**故意**写着
      `` 由 `now() - (i % 43200) minutes` 改为固定基准 `` —— 那是在说明**改掉了什么**。
      直接 `"now()" in text` 会在这里误报。正确做法：逐行 `line.split("--")[0]` 后再匹配。
   2. **`CREATE INDEX` 检查要限定在同一语句内**。`seed.sql` 有一行注释写着
      "不要在这里给 orders 的 tenant_id / created_at / customer_id / status 加任何索引"，
      正则如果跨行或只看 `orders` 关键字会误报。按行扫、只认以 `CREATE INDEX` 开头的语句。
2. 每道 `static` 的 sql 题，其 `verified_against` **必须提到 seed 文件路径**，否则红。
3. 幂等性：文件里 `TRUNCATE` 的每一张表，都必须在本文件里有对应的 `CREATE TABLE IF NOT EXISTS`。

> 为什么第 3 条重要：旧的 `sync_seed_primary.sql` 就是"假设别人会建表"，
> 结果那个"别人"不存在。**这条守门就是防止同样的坑再踩一次。**

### T1.5 我在真库上验收 `seed.sql` 的结论（2026-11-07，ZCode 初版）

我用**独立临时库** `p1_seed_probe`（不碰 `cloudagent_sim`）跑了 ZCode 的初版 `seed.sql`，
结果如下——**这条是给 ZCode 的确认，不是新的工作量**：

| 验收项 | 结果 |
|---|---|
| 首跑 | ✅ 全绿（orders 50000 / customers 2000） |
| **连跑第二次（幂等）** | ✅ exit 0，仅"已存在，跳过"提示；重放耗时 **0.58 秒** |
| 分布：tenant_id 1..50 各 1000 | ✅ `count(distinct)=50` |
| 分布：status 四值各 12500 | ✅ |
| 分布：region 四值各 500 | ✅ |
| 外键完整性（orders.customer_id → customers.id） | ✅ 0 空、0 越界、0 孤儿客户 |
| 索引清单 | ✅ 仅 `customers_pkey` / `idx_customers_region` / `orders_pkey`（**orders 无二级索引**） |
| 静态扫描：无 `now()` / 无 DSN / 有 ANALYZE / 无 orders 索引 | ✅ |
| sql-001..009 的 `plan_contains` | ✅ 全部命中（含 `Seq Scan` / `Bitmap Index Scan on idx_customers_region` / `Filter: (lower(region)` / `Index Scan using orders_pkey` / `Hash Join` / `Sort Key: amount DESC` / `date(created_at)`） |
| `TestGtReverification` 跑在这个 seed 库上 | ✅ **1 passed**（不是 skip） |

**结论：seed.sql 可以定为验收基线**，ZCode 继续做 T1.2/T1.3 时不必再回头改它。

#### 但有两个真缺陷要修（都在 `seed.sql` 里）

> **2026-11-07 追记**：这两条我都已在 `p1_def2` 临时库上**实测复现**，
> 且缺陷 1 比下面初稿描述的更严重（默认权限也被写进去了）。
> **以 [`reviews/p1-round1.md`](../reviews/p1-round1.md) 的缺陷 1/2 为准**，
> 下面保留原始判断过程供对照。

**缺陷 1（必须修）：`GRANT SELECT ON ALL TABLES IN SCHEMA public` 授权过宽**

`seed.sql:90` 用的是 `ALL TABLES IN SCHEMA public`。在同一台机器上，
`sync_seed_primary.sql` 会建 `tenants` / `devices`——两者共存于 `cloudagent_sim` 时，
本文件会**顺带把 sync 域的表也授权出去**，而本文件 docstring 又声称
"分工边界：tenants / devices 归 sync_seed_primary.sql，两份 seed 不重叠"。
**声明与行为不一致。**

修法（二选一，推荐前者）：
- `GRANT SELECT ON customers, orders TO cloudagent_ro;` —— 只授自己建的；
- 或 `GRANT SELECT ON ALL TABLES` 并**删掉**"不重叠"那句声明，承认它是全局授权。

站在"布局清晰、未来不吓人"的角度选**前者**：seed 只对自己建的东西负责。

**缺陷 2（必须修）：`TRUNCATE` 在"表已存在且有依赖对象"时会失败**

> **2026-11-07 更正**：我初稿判断"当前测试库没触发、这条属文档修补"——**判错了**。
> 实测触发条件是"有第三方表 FK 引用 orders/customers"，不是索引；
> 在 `p1_def2` 里 `CREATE TABLE audit_log(... REFERENCES orders(id))` 后重放 seed，
> 立即报 `在一个外键约束中无法删除 (truncate) 一个表的关联`，exit code 3。
> 详细复现与修法见 [`reviews/p1-round1.md`](../reviews/p1-round1.md) 缺陷 2。

在临时库里第 3 次重放时我试了带外键依赖更复杂的场景，发现：
如果有人在 `orders` 上加了视图/其它表的引用，`TRUNCATE orders, customers` 会报
`cannot truncate a table referenced in a foreign key constraint`。
当前测试库没触发（只有一条 FK），但**这条失败模式会在别的库上出现，且报错信息看不出是 seed 的问题**。

修法：显式写 `TRUNCATE orders, customers RESTART IDENTITY CASCADE;`
——不，**别加 `CASCADE`**（会静默清掉别人的表）。正确做法是**保留现状并在注释里写明
"本 seed 假定 orders/customers 上除彼此之外没有其它 FK 依赖；有则需先手工处理"**，
让失败信息与注释对得上。这一条属**文档修补**，不改 SQL。

> 我把这两条列进任务卡的「完成定义」，ZCode 修完再进 T1.2。

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
| ~~seed 的 `created_at` 改固定基准后，sql-002 的"近 1 天"可能变成 0 行，计划退化成 `Result`~~ **← 该论断已于 2026-11-07 实测证伪，见下方更正** | — |
| `TRUNCATE` 会清掉本机正在用的数据 | 只在 `cloudagent_sim` 上跑；**先在自己建的临时库验一遍幂等**（验收 ⑤） |
| 有人把 DSN 复制进仓库 | 静态守门 1 的第四项就是查这个 |

### 6.1 两次更正（都是我初稿的阶段性问题，实测推翻）

初稿 §6 我写过一条风险，随后又在修订中写成"这是假守卫"。**两次都不准确**，实测结论如下。
写在这里是为了让 ZCode 不要照着错论断做设计。

#### 更正一：空表/零命中**不会**退化成 `Result`（原风险条目作废）

```sql
-- 真表，filter 命中 0 行
EXPLAIN SELECT * FROM orders WHERE created_at > now() + interval '1 year';
-- → Seq Scan on orders (cost=0.00..1911.00 rows=5 width=56)

-- 完全空表（WITH NO DATA 建表 + ANALYZE）
EXPLAIN SELECT * FROM t_empty WHERE created_at > now() - interval '1 day';
-- → Seq Scan on t_empty (cost=0.00..0.00 rows=1 width=112)
```

PG 只对**能静态判定为空**的查询（`WHERE false` / `1=0`）才退化成 `Result`。
所以"seed 跑久了两天，`plan_contains: Seq Scan on orders` 会红"这个担心是**不成立的**。

#### 更正二：老化 24 天后断言**依然成立**，不是假守卫

我在修订稿里推演过"seed 跑完 30 天后近 1 天命中 0 行 → 断言恒真但不再证明原命题"。
**这个推理是对的，但结论说重了**。实测本机现状（seed 建于 2026-10-14，今天 2026-11-07，
已老化 **24 天**，`created_at` 最大值就是 24 天前）：

```
now() 与 max(created_at) 相差 24 天
近 1 天命中：0 行     近 7 天命中：0 行

EXPLAIN ... WHERE status = 'paid';
→ Seq Scan on orders (rows=12428)          ← sql-008 断言成立、且是真实选择性 25%

EXPLAIN ... WHERE status='paid' AND date(created_at) > current_date - 7 ...;
→ Limit → Sort (Sort Key: o.amount DESC) → Hash Join
    → Seq Scan on orders o  Filter: ((status='paid') AND (date(created_at) > (CURRENT_DATE - 7)))
                                             ← sql-009 的三个断言全部成立
```

**关键在于：这些断言验证的是"列上没有索引 ⇒ 优化器不会选索引"，不是"命中了多少行"。**
只要索引不存在，无论命中 0 行还是 12500 行，计划都是 `Seq Scan`；`Hash Join` 依赖的是
`customer_id` 无索引，也与时间窗口无关。所以断言**是稳健的机制断言**，不是数值断言。

→ **对 T1.1 的要求因此收敛为两条**（比我上一版轻）：

1. seed **仍然**改用固定基准时间，不用 `now()`——理由不是"断言会红"，而是**可复现**：
   同一份 seed 在不同日子跑出来的 `created_at` 分布应当一致，否则任何依赖分布的分析
   （比如"选择性 25%"）都会慢慢失真；
2. `verified_against` 里写清断言的**依据是索引缺失**，而不是行数。这一条比上一版更重要：
   它防止未来有人"看到命中 0 行就以为题目失效"而误改 gt。

`sql-002` / `sql-009` 的查询**保持原样**（`now()` / `current_date` 是真实业务写法，
改成固定日期反而失真）。

### 6.2 第三处更正：第三方 FK 会让 `TRUNCATE` 失败（初稿判错）

初稿缺陷 2 我写的是"当前测试库没触发（只有一条 FK）……这一条属**文档修补**，不改 SQL"。
**这个判断是错的**：触发条件不是"表上有几个索引"，而是**有没有第三方表 FK 引用
`orders` / `customers`**。实测（`p1_def2`）：

```sql
CREATE TABLE audit_log (id bigint, order_id bigint REFERENCES orders(id));
-- 然后 psql -f tests/fixtures/sql/seed.sql 重放：
--   错误: 在一个外键约束中无法删除 (truncate) 一个表的关联
--   DETAIL: 表"audit_log" 引用"orders".
--   exit code 3
```

这在真实 `cloudagent_sim` 上完全可能发生（sync 域的表就可能引用这些表），
所以它是会让人**在部署时突然撞上、且报错指不出是 seed 的问题**的缺陷。

→ **要求**：保留 `TRUNCATE orders, customers;`（**不加 `CASCADE`**，那会静默清空别人的表），
但必须**在注释里写明前提**："本 seed 假定 orders/customers 上除彼此之外无其它 FK 依赖；
若有，需先手工处理"。详细复现见 [`reviews/p1-round1.md`](../reviews/p1-round1.md) 缺陷 2。

**教训（给我自己）**：初稿这两条我都是靠"读代码 + 推理"下的判断，
而结论全靠**真跑一次**才得到——`now()` 那条推演多了两层、`TRUNCATE` 那条推演少了条件。
规格编写者不实测，写出来的"风险"就是猜。
