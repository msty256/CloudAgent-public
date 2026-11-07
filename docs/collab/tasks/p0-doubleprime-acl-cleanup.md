# P0'' 任务卡：清理 `cloudagent_sim_downstream` 的默认权限残留

| 项 | 值 |
|---|---|
| 工作包 | P0'' |
| 状态 | `done`（2026-11-07 审查 PASS，数据库已验证） |
| 负责人 | ZCode |
| 分支 | 无（只动数据库 + 写记录） |
| 预估 | **10 分钟** |
| 依赖 | 无。可与 P4a/P2a/EVAL-P0 的合并并行 |

> 来源：P0' handoff「红线遵守情况」第 2 条，ZCode 主动报告。我已实测确认。

## 问题

P0' 清了上游库 `cloudagent_sim` 的 `pg_default_acl`，但**下游库有同样的残留**：

```
cloudagent_sim_downstream: pg_default_acl = [('postgres', 'public', 'r', ['cloudagent_ro=r/postgres'])]
```

含义与上游相同：**今后任何人在下游库的 `public` 建表，`cloudagent_ro` 会自动获得 SELECT**。

ZCode 在 P0' 里按红线 2「不许动下游库」没有动它，只报告——**判断正确**。

## 要做的事

### 步骤 1：确认改前状态（存档到 handoff）

```powershell
$sp = ((Get-Content "$env:USERPROFILE\.cloudagent\db_sim.env") |
    Where-Object { $_ -match '^CLOUDAGENT_DB_SUPERPASSWORD=' }) -replace '^CLOUDAGENT_DB_SUPERPASSWORD=',''
$env:PGPASSWORD = $sp
$psql = "C:\Program Files\PostgreSQL\16\bin\psql.exe"

# ① 默认权限
& $psql -h 127.0.0.1 -p 5433 -U postgres -d cloudagent_sim_downstream -w `
  -c "select defaclrole::regrole, defaclnamespace::regnamespace, defaclobjtype, defaclacl from pg_default_acl;"

# ② 表级 ACL（改前基线，必须保持不变）
& $psql -h 127.0.0.1 -p 5433 -U postgres -d cloudagent_sim_downstream -w `
  -c "select relname, relacl from pg_class where relkind='r' and relnamespace='public'::regnamespace order by 1;"
```

**我 2026-11-07 实测的现状**：① 1 行；② 4 张表（customers/devices/orders/tenants）
各带 `cloudagent_ro=r/postgres`。**与你实测的若有出入，以你的为准并注明**。

### 步骤 2：执行（与 P0' 同一条命令，只换库名）

```sql
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM cloudagent_ro;
```

### 步骤 3：验证

```powershell
# ① 必须 0 行
& $psql ... -d cloudagent_sim_downstream -c "select * from pg_default_acl;"

# ② 4 张表 relacl 与步骤 1 逐字一致（零误伤）
& $psql ... -d cloudagent_sim_downstream -c "select relname, relacl from pg_class where ..."

# ③ 探针：新建表后只读角色读不到
& $psql ... -d cloudagent_sim_downstream -c "CREATE TABLE _acl_probe2(id int);"
$env:PGPASSWORD = <ro password>
& $psql -h 127.0.0.1 -p 5433 -U cloudagent_ro -d cloudagent_sim_downstream -w -c "select * from _acl_probe2;"
# 期望：permission denied for table _acl_probe2
$env:PGPASSWORD = <super password>
& $psql ... -d cloudagent_sim_downstream -c "DROP TABLE _acl_probe2;"

# ④ 业务表仍可读（不能误伤 sync 域）
& $psql -h 127.0.0.1 -p 5433 -U cloudagent_ro -d cloudagent_sim_downstream -w `
  -c "select (select count(*) from devices) devices, (select count(*) from tenants) tenants;"
# 期望：devices 50 / tenants 8（下游有 8 行租户，这是 sync 域的对照基准）
```

### 步骤 4：写记录

新建 `docs/collab/handoffs/p0-doubleprime-acl-cleanup.md`，含改前/改后原始输出。
**不产生代码提交**。

## 完成定义

- [ ] `cloudagent_sim_downstream` 的 `pg_default_acl` 返回 **0 行**
- [ ] 4 张表 `relacl` 与改前**逐字一致**
- [ ] `_acl_probe2` 探针：只读角色读不到（permission denied）
- [ ] 只读角色仍能读 `devices`(50) / `tenants`(8) / `orders`(0) / `customers`(0)
- [ ] handoff 写好，含改前/改后输出
- [ ] **没有任何仓库代码提交**

## 红线

1. **不许 REVOKE 表级授权**——sync 域要读下游的 `devices`/`tenants`。
2. **不许动上游 `cloudagent_sim`**（P0' 已处理完，不要重复动）。
3. **不许把凭据写进任何文件**。
4. 如果下游 `pg_default_acl` 里**不止一条**（比如还有序列 `defaclobjtype='S'`），
   **停下来报告**，不要一并 REVOKE。
5. 如果发现**其它库**（如 `postgres` / `template1`）也有同样残留，
   **报告，不要顺手改**——逐个确认后再动。
