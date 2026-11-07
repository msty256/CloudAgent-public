# P0'' 审查结论：清理 `cloudagent_sim_downstream` 默认权限残留

> 审查人：DSH Lead · 2026-11-07 · 提交 `49f726a`（直接提交到 `main`）

## 结论：`PASS`

清理已生效，零误伤，红线全部遵守。**并且做了一件我没要求但正确的事**（见 §3）。

---

## 1. 我实际做了什么验证

**没有只读 handoff——直接查了数据库**（这是本卡唯一可信的验收方式）：

```sql
-- 下游库
select * from pg_default_acl;
--  oid | defaclrole | defaclnamespace | defaclobjtype | defaclacl
-- -----+------------+-----------------+---------------+-----------
-- (0 rows)                                                    ✅ 原 1 行

select relname, relacl from pg_class
where relkind='r' and relnamespace='public'::regnamespace order by 1;
-- customers | {postgres=arwdDxt/postgres,cloudagent_ro=r/postgres}   ✅
-- devices   | {postgres=arwdDxt/postgres,cloudagent_ro=r/postgres}   ✅
-- orders    | {postgres=arwdDxt/postgres,cloudagent_ro=r/postgres}   ✅
-- tenants   | {postgres=arwdDxt/postgres,cloudagent_ro=r/postgres}   ✅
```

**4 张表 relacl 逐字未变**，`tenants`/`devices` 的 SELECT 保住了
（这正是任务卡里强调"不能收"的部分——sync 域要读）。

## 2. 红线复核

| 红线 | 状态 | 我的验证 |
|---|---|---|
| 不许 REVOKE 表级授权 | ✅ | 上面 relacl 查询，4 表全在 |
| 不许动上游 `cloudagent_sim` | ✅ | 上游 `pg_default_acl` 仍 0 行（P0' 成果完好） |
| 不许把凭据写进文件 | ✅ | handoff 全文无 DSN/密码值 |
| `pg_default_acl` 不止一条就要停 | ✅ | 改前仅 1 条（`defaclobjtype='r'`），无序列条目 |
| 其它库同类残留只报告 | ✅ | 扫了 `cloudagent_sim` / `postgres`，均 0 行；模板库未扫并注明 |

## 3. 做得比我要求的多（且正确）

任务卡只要求处理下游库。ZCode **主动扫描了其它库**：

```
databases: ['cloudagent_sim', 'cloudagent_sim_downstream', 'postgres']
  [cloudagent_sim]          pg_default_acl rows = 0   ← P0' 成果在
  [postgres]                pg_default_acl rows = 0
  （template0/template1 为模板库未扫）
```

这是有价值的信息：它排除了"还有第三处残留"的可能，而这不是本卡范围。
**主动扩大确认范围、但严格不改动范围外的对象**——这个分寸拿得很准。

## 4. 手法说明（我认可）

- `relacl` 用 `== ` **全等断言**比对改前快照，不是人工目测；
- 探针表 `_acl_probe2` 验证"新建表只读角色不可读"（这是"清干净了"的行为证据，
  比只看 ACL 查询更有说服力）；
- 本机 PATH 无 `psql`，用 psycopg 以 superuser 执行等价 SQL——与 P0' 同样处理，
  已在 handoff 里说明。

## 5. 无遗留问题

| 项 | 状态 |
|---|---|
| 上游库 | 已清（P0'） |
| 下游库 | 已清（本卡） |
| `postgres` 库 | 无残留 |
| 模板库 | 未扫（合理，不会有人在模板库建业务表） |

→ **ACL 相关的技术债到此清零。**

## 6. 一个流程上的自我批评

这张卡你（ZCode）在 handoff 末尾标了 `in_review` 等审查，而我在合并四个包时
**没有单独给 P0'' 出审查结论**，只写进了任务板状态。导致你按约定等待。

**这是我的疏漏。** 已在本次补齐，并把五个已完成包的任务卡状态统一改成 `done`
（之前只改了任务板，卡片本身还挂着 `in_review` / `in_progress`，同样是我的问题）。

**改进**：今后每个包一旦判定 PASS，必须同时做三件事——
① 写 `reviews/<task-id>-roundN.md`；② 改任务卡状态；③ 改任务板。
缺任何一件，等待方（你或我）就会卡住。
