# P0'' 交接说明：清理 `cloudagent_sim_downstream` 的默认权限残留

> ZCode · 2026-11-07 · 无分支、无代码提交（按任务卡：只动下游库 + 本记录）

## 结论

下游库的历史残留默认授权已清除：`pg_default_acl` 从 1 行 → **0 行**；4 张表的表级
ACL 与改前**逐字一致**（零误伤）；探针验证"新建表只读角色不可读"成立；sync 域
基准数据可读性不变（devices 50 / tenants 8 / orders 0 / customers 0）。
工具说明：本机 PATH 无 `psql`，用 psycopg 以 superuser 执行等价 SQL（与任务卡
命令语义一致，同 P0'）。

## 步骤 1：改前状态（原始输出存档）

```
===== cloudagent_sim_downstream
pg_default_acl: [('postgres', 'public', 'r', ['cloudagent_ro=r/postgres'])] | rows = 1
   ('customers', ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
   ('devices',   ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
   ('orders',    ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
   ('tenants',   ['postgres=arwdDxt/postgres', 'cloudagent_ro=r/postgres'])
```

与任务卡 Lead 实测一致（1 行、类型 `r`、无序列条目——红线 4 前提满足）。

## 红线 5：其它库同类残留扫描（只报告）

```
databases: ['cloudagent_sim', 'cloudagent_sim_downstream', 'postgres']
  [cloudagent_sim]          pg_default_acl rows = 0   ← P0' 成果在
  [postgres]                pg_default_acl rows = 0
```

（template0/template1 为模板库未扫。）**除下游外无其它残留**，无需再报。

## 步骤 2：执行

```sql
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM cloudagent_ro;
-- 目标库：cloudagent_sim_downstream（未触碰上游，红线 2）
```

## 步骤 3：改后验证（原始输出存档）

```
pg_default_acl after: [] | rows = 0                      ← 完成定义 ① ✅
relacl identical to before: OK                           ← 完成定义 ② ✅（逐字一致断言）
PROBE OK: ro -> _acl_probe2: 对表 _acl_probe2 权限不够      ← 完成定义 ③ ✅
ro reads -> devices=50 tenants=8 orders=0 customers=0     ← 完成定义 ④ ✅（sync 域基准不变）
```

relacl 用 `== ` 全等断言比对改前快照，非人工目测。

## 红线遵守情况

1. ✅ 未 REVOKE 任何表级授权（全等断言证明）；
2. ✅ 未动上游 `cloudagent_sim`；
3. ✅ 凭据全部来自仓库外 `~/.cloudagent/db_sim.env`，未写入任何文件；
4. ✅ 改前仅 1 条（类型 `r`），无需停下报告；
5. ✅ 其它库已扫（见上），无同类残留。

## 没做的事

- 未写可复用脚本（沿用 P0' 的口径：先问 Lead）；
- 未动任何模板库。
