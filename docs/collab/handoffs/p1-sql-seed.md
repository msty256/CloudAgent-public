# P1 交接说明：sql 域取证基线（11 题 runtime → static）

> ZCode · 2026-11-07 · 分支 `feat/p1-sql-seed`
> 状态：已完成 round-1 审查缺陷修复，等 Lead 二审。

## 1. 改了什么

| 文件 | 改动 |
|---|---|
| `tests/fixtures/sql/seed.sql`（新增） | orders/customers 种子，仓库内唯一权威来源。幂等（TRUNCATE + 重灌），`created_at` 固定基准 `2026-10-14 00:00:00+08` 往前推 ~30 天，文件头显式声明 F1–F6 六条被断言依赖的事实 |
| `cloudagent_ext/diagnosis/cases/sql/sql-00{1..9}/013/014.json` | `verification` runtime→static、`verified_at` 2026-11-07、`verified_against` 统一为「seed 路径 + 2026-11-07 实测：<依据>」 |
| `tests/diagnosis/test_case_meta.py` | 锁死数字 17/15/6 → 28/4/6；`test_static_set_is_exact` 加入 11 个 id；注释记录口径变更史 |
| `tests/diagnosis/test_sql_seed_contract.py`（新增） | 不依赖 PG 的静态守门，8 条测试（见 §4） |

提交序列（每步全量测试均绿）：

```
55a2e0d feat(p1): sql 域 seed 迁入本仓（幂等 + created_at 固定基准）
cac03e9 feat(p1): sql 域 11 题 runtime → static，锁死分布 17/15/6 → 28/4/6
3487931 test(p1): sql 域 seed 契约的静态守门（不依赖 PG）
89f57e9 fix(p1): 按 round-1 审查修 seed 授权过宽与 TRUNCATE 前提，守门补滚动时间检查
```

## 2. 为什么这么改（关键取舍与被否方案）

- **固定基准 vs 改写 sql-002/009 的查询**：选了固定基准、案例 SQL 原样保留
  （`now()` / `current_date` 是真实业务写法）。Lead 追加的 §6.1 更正与我的实测
  一致：断言是"无索引 ⇒ 不选索引"的机制断言，与命中行数无关；固定基准的
  意义是**分布可复现**，不是断言存活。规格 §6 原预警的"计划退化成 Result"
  经真库 EXPLAIN 证伪（预估计划不做常量折叠，Filter 保留）。
- **TRUNCATE 缺陷修复选 A 不是 CASCADE**（审查推荐 A）：CASCADE 会静默清空
  引用 orders/customers 的第三方表，共享库上不可接受；保留失败 + 注释写明前提。
- **GRANT 收窄 + 删 ALTER DEFAULT PRIVILEGES**（审查缺陷 1）：seed 只对自己建的
  表负责。修后新临时库 `pg_default_acl` = 0 条、cloudagent_ro 恰好只有
  customers/orders 两表 SELECT（实测）。
- **JSON 用整行替换而非重序列化**：每文件恰好 3 行 diff（verification /
  verified_at / verified_against），其余字节不动，审查 diff 最小化。
- **`verified_against` 写依据不写数值**：按规格 T1.2 修订要求，依据一律是
  "某列无索引"（机制事实）；初版里 sql-002 的"估算 rows=5"、sql-008 的
  "估算 rows=12415"属于会随时间漂移的数值，已移除（选择性 ~25% 保留——
  它来自 seed 分布 F3/F4，是稳定事实）。
- **静态守门的滚动时间检查**照审查参考实现：先 `line.split("--")[0]` 剥注释再扫
  （D2 注释里故意写着 `now()`）；`CREATE INDEX` 检查本来就是按行首匹配，
  注释行不会被误报。

## 3. 验收命令逐条结果（全绿）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `pytest tests/diagnosis/test_sql_seed_contract.py -q` | **8 passed** |
| 2 | `pytest tests/diagnosis/test_case_meta.py -q` | **12 passed** |
| 3 | `pytest tests/diagnosis -q --no-header -p no:cacheprovider` | **836 passed / 24 skipped**（基线 828+24，+8 新增） |
| 4 | `python -m cloudagent_ext.diagnosis.case_audit` | **现在就能复核 28 / 需运行期环境 4 / 无法复核 6** |
| 5 | GtReverification（配 `CLOUDAGENT_DB_DSN`） | **1 passed（非 skip）** |
| 6 | `ruff check test_sql_seed_contract.py test_case_meta.py` | All checks passed |
| 7 | seed 临时库连跑两次（新库 `cloudagent_sim_p1check`，已 DROP） | 两遍快照一致（幂等）；11 题 **19 条断言全部成立** |
| 8 | 回归：`tests/context` / `tests/tool_system` | 165 passed / 115 passed（与基线一致） |

注：验收 ⑤ 的 `psql` 本机不在 PATH，用 psycopg autocommit 多语句执行等价完成
（简单查询协议，与 psql -f 同语义）。临时库验证脚本在仓库外
`~/.zcode/tmp/p1-verify/`，未入仓。

## 4. 新增/改动的测试与守门逻辑

`test_sql_seed_contract.py`（8 条，无 DSN 环境全跑）：

1. `test_no_index_on_forbidden_order_columns`——CREATE INDEX 行不出现四禁列
   （含"正则确实扫到了索引行"的自身健全性断言，防空转）；
2. `test_customers_region_index_created`；
3. `test_analyze_present`；
4. `test_no_credentials`——无 `postgresql://`、无 password（大小写不敏感）；
5. `test_no_rolling_time_in_seed`——剥注释后无 `now(` / `current_date` /
   `current_timestamp`（D2 回归守门）；
6. `test_p1_upgrade_set_still_static`——P1 的 11 题必须仍是 static（下界，
   防守门空转）；
7. `test_verified_against_cites_seed_path`——每道 static 的 sql 题引用
   `tests/fixtures/sql/seed.sql`；
8. `test_every_truncated_table_is_created_in_file`——TRUNCATE 的表必有
   CREATE TABLE IF NOT EXISTS（sync_seed_primary 当年的坑）。

`test_case_meta.py`：数字与集合同步（这是验收点，不是"改测试变绿"）。

## 5. seed 建库上的断言实测片段（临时库，2026-11-07）

```
sql-001  Seq Scan on orders (cost=0.00..1661.00 rows=988)
           Filter: (tenant_id = 7)                        + index_absent tenant_id ✔
sql-002  Seq Scan on orders (cost=0.00..1911.00 rows=5)
           Filter: (created_at > (now() - '1 day'::interval))   ✔（见 §6 疑问 2）
sql-003  Bitmap Heap Scan on customers → Bitmap Index Scan on idx_customers_region
           Index Cond: (region = 'north'::text)           + index_present ✔
sql-004  Seq Scan on customers rows=10
           Filter: (lower(region) = 'north'::text)        + index_present ✔
sql-005  Limit → Index Scan using orders_pkey on orders ✔
sql-006  Hash Join (Hash Cond: (o.customer_id = c.id))
           → Seq Scan on orders o Filter: (tenant_id = 3) + index_absent customer_id ✔
sql-007  Limit → Sort (Sort Key: amount DESC) → Seq Scan on orders ✔
sql-008  Seq Scan on orders rows=12415
           Filter: (status = 'paid'::text)                + index_absent status ✔
sql-009  Limit → Sort (Sort Key: o.amount DESC) → Hash Join
           → Seq Scan on orders o Filter: ((status='paid') AND
             (date(created_at) > (CURRENT_DATE - 7)))     + index_absent created_at ✔
sql-013  get_lock_info → waiting: [] ✔
sql-014  get_table_stats(customers) → n_live_tup=2000, region n_distinct=4.0 ✔
```

## 6. 还没做的事（诚实清单）

1. **我在 round-1 审查送达之前，已把（初版）seed 重放到 `cloudagent_sim`**——
   目的是让本机库状态与仓库内 seed 严格同源。数据形状与重放前完全一致
   （旧 seed 的 2026-10-14 基线 + 同一生成式），GtReverification 重放后 1 passed。
   若 Lead 认为不该动，`sync_seed_primary.sql` + 旧 seed 可完整复原现场，请示下。
2. **`cloudagent_sim` 上残留旧授权**：缺陷 1 修复只约束**今后**的 seed 执行；
   库里现存的 `GRANT ALL TABLES` 后果与 `pg_default_acl` 条目来自 2026-10-14
   旧仓 seed（我重放用的初版也带这两行）。REVOKE / 清 ACL 不在 P1 写入范围，
   归属（bootstrap？sync seed？一次性手工？）请 Lead 裁决，我可代跑。
3. **tenants/devices 未灌数**：按规格 §5 归 `sync_seed_primary.sql` 职责，未越界。
4. **`sql-010/011/012`、`sync-001` 保持 runtime**：非数据问题，升 static 是撒谎。

## 7. 规格疑问（请 Lead 裁决）

1. **`verified_at` 我一并改了**（2026-11-01 → 2026-11-07）。任务卡写入范围只列了
   verification/verified_against；但 static 元数据若留着旧日期会与证据日期矛盾。
   属同一文件同一块元数据的一行改动，判断为范围精神之内——不同意可一键还原。
2. **审查"特别肯定"引用的 sql-002 文本含"估算 rows=5"**，而设计文档 T1.2 修订
   把"会漂移的数值"列为反例；我按后者移除了 rows=5、保留了全部实质
   （依据=无索引、0 行不退化、不做常量折叠）。若 Lead 认为估算行数作为
   "当时观测值"值得保留，我改回。
3. **验收 ⑤ 的"跑完再验一次"**我执行为：重放 cloudagent_sim → GtReverification
   + 全量 pytest。与规格字面（psql 临时库）路径不同但语义覆盖，见 §3 注。

## 8. 给二审的索引

- round-1 缺陷 1/2/3 的修复与复验：§2、§3、§4；
- Lead 真库验收过的项（幂等/分布/FK/索引清单/sql-001..009 计划/GtReverification）
  未重做，仅在**修后新临时库**上重验了幂等与 19 条断言；
- 任务卡「完成定义」两条【新增】项均已落地（GRANT 收窄、TRUNCATE 前提注释）。
