# P0' 任务卡：清理 `cloudagent_sim` 的 `pg_default_acl` 残留

| 项 | 值 |
|---|---|
| 工作包 | P0' |
| 状态 | `in_review`（清理完成，待审；2026-11-07 ZCode） |
| 负责人 | ZCode |
| 分支 | 无（本卡**不改仓库代码**，只动本机数据库 + 写一份记录） |
| 预估 | **20 分钟** |
| 依赖 | 无 |

> 来源：P1 handoff §6 第 2 条，ZCode 主动报告的遗留问题。我在 round-2 审查中实测确认。

## 问题

`cloudagent_sim` 库里存在一条**历史残留的默认权限**：

```
postgres | public | r | {cloudagent_ro=r/postgres}
```

含义：**今后任何人在 `public` 建表，`cloudagent_ro` 会自动获得 SELECT**。

来源：2026-10-14 的旧 seed（以及 ZCode 在审查送达前重放的初版 seed）里那句
`ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cloudagent_ro;`。

**P1 已经把这句话从 seed 里删掉了**——那只约束"今后执行"，
**不清已经写进数据库的存量**。所以要单独清一次。

## ⚠️ 范围必须精确：只清默认权限，不动表级授权

我第一版判断"授权全都要收"，实测后**修正**：

| 对象 | 该不该动 | 理由 |
|---|---|---|
| `pg_default_acl` 里那条 | ✅ **清掉** | 这是隐式的、持久的、会扩散到未来所有表的授权 |
| `cloudagent_ro` 对 `orders` / `customers` 的 SELECT | ❌ **保留** | sql 域诊断必需 |
| `cloudagent_ro` 对 `tenants` / `devices` 的 SELECT | ❌ **保留** | **sync 域诊断必需**（sync-004/005 要读 devices）；`CLOUDAGENT_DB_QUERYABLE_TABLES = public.*` |

**收掉表级授权会让 sync 域直接坏掉。** 这条要写清楚，防止 ZCode"顺手把权限都收了"。

## 要做的事

### 步骤 1：确认当前状态（贴输出）

```powershell
# 读凭据（仓库外，绝不复制进仓库）
$env:PGPASSWORD = ((Get-Content "$env:USERPROFILE\.cloudagent\db_sim.env") |
    Where-Object { $_ -match '^CLOUDAGENT_DB_SUPERPASSWORD=' }) -replace '^CLOUDAGENT_DB_SUPERPASSWORD=',''
$psql = "C:\Program Files\PostgreSQL\16\bin\psql.exe"

# ① 默认权限
& $psql -h 127.0.0.1 -p 5433 -U postgres -d cloudagent_sim -w `
  -c "select defaclrole::regrole, defaclnamespace::regnamespace, defaclobjtype, defaclacl from pg_default_acl;"

# ② 表级 ACL（作为清理后的对照基线，必须保持不变）
& $psql -h 127.0.0.1 -p 5433 -U postgres -d cloudagent_sim -w `
  -c "select relname, relacl from pg_class where relkind='r' and relnamespace='public'::regnamespace order by 1;"
```

**期望的现状**（我 2026-11-07 08:xx 实测）：
- ① 有 1 行：`postgres | public | r | {cloudagent_ro=r/postgres}`
- ② 4 张表（customers/devices/orders/tenants）各带 `cloudagent_ro=r/postgres`

**先存档 ① ② 的原始输出到 handoff**，这是"改之前"的证据。

### 步骤 2：清默认权限

```powershell
& $psql -h 127.0.0.1 -p 5433 -U postgres -d cloudagent_sim -w `
  -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM cloudagent_ro;"
```

### 步骤 3：验证

```powershell
# ① 必须变成 0 行
& $psql ... -c "select * from pg_default_acl;"

# ② 表级 ACL 必须与步骤 1 的存档**逐字节一致**（证明没误伤）
& $psql ... -c "select relname, relacl from pg_class where ..."

# ③ 行为验证：新建一张表，确认 cloudagent_ro 读不到
& $psql ... -d cloudagent_sim -c "CREATE TABLE _acl_probe(id int);"
$env:PGPASSWORD = <ro password>
& $psql -h 127.0.0.1 -p 5433 -U cloudagent_ro -d cloudagent_sim -w -c "select * from _acl_probe;"
# 期望：ERROR: permission denied for table _acl_probe   ← 这才是"清干净了"
$env:PGPASSWORD = <super password>
& $psql ... -d cloudagent_sim -c "DROP TABLE _acl_probe;"

# ④ 只读角色对业务表仍然可读（不能误伤）
& $psql -h 127.0.0.1 -p 5433 -U cloudagent_ro -d cloudagent_sim -w `
  -c "select count(*) from orders; select count(*) from customers; select count(*) from devices;"
# 期望：50000 / 2000 / 50 —— 三张表都可读
```

### 步骤 4：写记录（不改仓库代码，只加文档）

新建 `docs/collab/handoffs/p0-prime-acl-cleanup.md`，包含：
- 步骤 1 的原始输出（改前）
- 步骤 3 的验证输出（改后）
- 一句话结论

**本卡不产生代码提交**，只产生这一份 handoff。
（如果你觉得该把这条清理写成可复用脚本，**先问我**——那属于新工作，不在本卡。）

## 完成定义

- [ ] `pg_default_acl` 查询返回 **0 行**
- [ ] 4 张表的 `relacl` 与改前**完全一致**（没误伤）
- [ ] `_acl_probe` 探针验证：新建表后只读角色读不到（permission denied）
- [ ] 只读角色仍能读 `orders`(50000) / `customers`(2000) / `devices`(50)
- [ ] `docs/collab/handoffs/p0-prime-acl-cleanup.md` 写好了，含改前/改后输出
- [ ] **没有**任何仓库代码提交

## 红线

1. **不许 `REVOKE` 表级授权** —— 会让 sync 域坏掉。
2. **不许动 `cloudagent_sim_downstream`** —— 本卡只处理上游库。
   如果下游也有同样的残留，**报告，不要顺手改**。
3. **不许把凭据写进任何文件**（含 handoff）。上面的命令只是示例，
   实际执行时从 `~/.cloudagent/db_sim.env` 读，**不要把值粘进文档**。
4. 如果 `pg_default_acl` 里**不止一条**（比如还有 `defaclobjtype='S'` 序列的），
   **停下来报告**，不要一并 REVOKE。
