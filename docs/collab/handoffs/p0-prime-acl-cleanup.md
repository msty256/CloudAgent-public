# P0' 交接说明：清理 `cloudagent_sim` 的 `pg_default_acl` 残留

> ZCode · 2026-11-07 · 无分支、无代码提交（按任务卡：只动数据库 + 本记录）

## 结论

`cloudagent_sim` 的历史残留默认授权已清除：`pg_default_acl` 从 1 行 → **0 行**；
4 张表的表级 ACL 与改前**逐字一致**（零误伤）；探针表验证"新建表只读角色不可读"成立；
只读角色对业务表可读性不变。**工具偏离说明**：本机 PATH 无 `psql`，用 psycopg
以 superuser 执行等价 SQL（与任务卡命令语义一致）。

## 步骤 1：改前状态（原始输出存档）

```
===== cloudagent_sim
pg_default_acl: [('postgres', 'public', 'r', ['cloudagent_ro=r/postgres'])]
   ('customers', ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
   ('devices',   ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
   ('orders',    ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
   ('tenants',   ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
```

与任务卡预期一致：仅 1 条默认权限（`defaclobjtype='r'`，无序列类条目，
满足红线 4 的"不止一条即停"前提）；4 张表各带 `cloudagent_ro=r/postgres`。

## 步骤 2：执行

```sql
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM cloudagent_ro;
```

## 步骤 3：改后验证（原始输出存档）

```
pg_default_acl after: [] | rows = 0                     ← 完成定义 ①：0 行 ✅
   ('customers', ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
   ('devices',   ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
   ('orders',    ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
   ('tenants',   ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
                                                        ← 完成定义 ②：逐字一致 ✅
```

行为验证：

```
CREATE TABLE _acl_probe(id int)  （superuser）
cloudagent_ro 读 _acl_probe → psycopg.errors.InsufficientPrivilege:
    对表 _acl_probe 权限不够                             ← 完成定义 ③ ✅
DROP TABLE _acl_probe

cloudagent_ro 读业务表：
    orders    50000                                     ← 完成定义 ④ ✅
    customers  2000
    devices      50
```

## 红线遵守情况

1. ✅ 未 REVOKE 任何表级授权（relacl 对照逐字一致）；
2. ⚠️ **未动 `cloudagent_sim_downstream`，但实测它有同样的残留**（按红线 2 只报告）：
   `pg_default_acl: [('postgres', 'public', 'r', ['cloudagent_ro=r/postgres'])]`，
   4 张表 relacl 与上游相同。是否清理由 Lead 决定，清理命令与本次相同；
3. ✅ 凭据全部从仓库外 `~/.cloudagent/db_sim.env` 读取，未写入任何文件；
4. ✅ `pg_default_acl` 改前仅 1 条，无需停下报告。

## 没做的事

- 未写可复用脚本（任务卡明示：要先问 Lead）；
- 未动下游库（见红线 2 报告项）。
