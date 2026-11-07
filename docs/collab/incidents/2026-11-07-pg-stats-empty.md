# 环境事故记录：`pg_stat_user_tables` 累计统计为空

> 发现：2026-11-07 11:20 · 处理：11:26 · 影响：1 条测试误报 · **与代码无关**

## 现象

合并三个分支后跑联合验收，`tests/diagnosis` 报 1 条失败，且**两次跑失败位置不同**：

```
第一次：test_code_log_cases.py::TestGtReverification::test_code_tool_called
第二次：test_case_library.py::TestGtReverification::test_verifiable_cases_match_ground_truth
        AssertionError: sql-014: n_live_tup expected 2000, got 0
```

单独跑那两条却都通过（其中一条耗时 34.9 秒）。

## 定位过程（三步排除）

### 1. 先排除"是不是合并引入的"

```powershell
git worktree add $env:TEMP\pre-merge-check 845b232   # 合并前的 main
# 在该 worktree 上跑同一测试
→ 1 failed   ← 合并前也失败
```

**结论：与三个分支无关。** 这条是最关键的证据——没有它就会误判成合并引入的回归。

### 2. 再定位到具体数据源

失败点读的是 `n_live_tup`。查 `postgres.py::fetch_table_stats` 的实现：

```sql
SELECT c.reltuples, ..., s.n_live_tup, ...
FROM pg_class c
LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
```

**两个数据源，状态不一致**：

| 来源 | 值 | 是否正确 |
|---|---|---|
| `pg_class.reltuples`（ANALYZE 产物） | orders 50000 / customers 2000 | ✅ |
| `pg_stat_user_tables.n_live_tup`（后台统计收集器） | **全部 0** | ❌ |

真实行数 `count(*)` 也是对的（50000 / 2000），所以**数据没丢，只是累计统计没采到**。

### 3. 确认不是"延迟"

```sql
select datname, stats_reset from pg_stat_database where datname='cloudagent_sim';
→ stats_reset = 空
```

`stats_reset` 为空表示**从未重置过**——不是被重置，而是这些表的累计统计从来就没有被采集到
（`UPDATE`/`INSERT` 计数走的不是这条路径，或统计收集器在此实例上没正常累积）。

等了 15 秒重查，仍全 0 → 不会自愈。

## 处置

按项目所有者确认，执行（**只重建统计，不动数据**）：

```sql
ANALYZE orders; ANALYZE customers; ANALYZE devices; ANALYZE tenants;
```

结果：

```
relname   | n_live_tup | last_analyze
customers |       2000 | 2026-11-07 11:25:44
devices   |         50 | 2026-11-07 11:25:44
orders    |      50000 | 2026-11-07 11:25:44
tenants   |          0 | 2026-11-07 11:25:44
```

⚠️ 一个细节：改后我特意**用只读角色 `cloudagent_ro` 复验了一遍**——
因为 `pg_stat_*` 视图对普通角色也可见，但要确认权限没挡住。结果一致。

## 验证

| 场景 | 结果 |
|---|---|
| `GtReverification`（配 DSN） | **1 passed**（修前 failed） |
| `tests/diagnosis` + DSN | **878 passed / 7 skipped** |
| `tests/diagnosis` 无 DSN | **861 passed / 24 skipped** |
| `tests/{context,tool_system,utils,agent}` | **635 passed / 3 skipped** |
| `ruff check cloudagent_ext tests` | **All checks passed!** |

**skip 数从 24 降到 7**：修好后 DB 相关测试真正跑起来了，不再因为统计异常而跳过。

## 教训（写下来防止重复排查）

1. **`n_live_tup` 与 `reltuples` 是两个来源，会不一致。** 前者来自后台统计收集器，
   后者来自 `ANALYZE`。评测断言用 `n_live_tup` 就意味着**依赖一个可能为空的累计计数器**。
2. **`tests/diagnosis` 全量跑时的失败位置会漂移**（两次不同），这是"环境态"的典型症状——
   真回归通常是稳定复现同一个点。**失败位置漂移 → 先怀疑环境，再怀疑代码**。
3. **用 worktree 对比合并前后，是排除"是不是合并引入的"最快的手段**（1 分钟）。
4. 本机 `cloudagent_sim` 是**手工维护的仿真库**，不是由 seed 每次都重建的。
   任何"统计类"断言都可能因库的生命周期而失效。

## 对后续工作的影响

- **EVAL-P2（等价性迁移）**：历史 run 的 `get_table_stats` 证据里若含 `n_live_tup=0`，
  那是当时的真实观测，**不要按新状态改写**。
- **sql-014** 的 `verified_against` 写的是 `n_live_tup=2000`，依赖统计新鲜。
  这与 P1 的"断言写机制依据不写数值"原则**有张力**——它确实是数值断言。
  已在 P1 审查记录里接受（该题 GT 本身就是"统计信息是否新鲜"），但
  **它比其它题更容易因环境漂移而红**，这是一条已知脆弱点。
- **P0''（下游库清理）** 若在那里也跑 ANALYZE，注意下游 `orders/customers` 是 0 行，
  统计本就是 0，别误判成同样的事故。
