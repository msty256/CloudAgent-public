# P1–P4 旧任务与新评测体系的关系评估

> 日期：2026-11-07 · 作者：DSH Lead
> 问题：新评测体系（[`eval-system-design.md`](./eval-system-design.md)）立项后，
> 原 P1–P4 四个工作包该**直接并入**、**拆分**、还是**作废**？

---

## 0. 结论速览

| 原任务 | 当前状态 | 判定 | 处置 |
|---|---|---|---|
| **P1** sql seed + 11 题 `runtime→static` | **已完成，待二审** | ✅ **全量并入**（作为新体系的 golden 基线） | 先合并；日后 `git mv` 到评测仓 |
| **P2** 开关泄漏守卫泛化 | `blocked`（未开工） | ⚠️ **拆分** | 产品半边保留原样；评测半边并入新体系 runner |
| **P3** 多臂预设 | `blocked_by: P2`（未开工） | ❌ **不在产品仓实现** | 设计思路并入新体系实验层；代码不写 |
| **P4** 评测链路缺陷收口 | `ready`（未开工） | ⚠️ **拆分** | F821 两行现在就做；Bash 修复迁到 `eval_support`；截断判定并入评测仓 |

**一句话**：旧的 P2/P3/P4 有一半写的是**即将被删除的代码**
（`cloudagent_ext/diagnosis/evaluation/`，219.8 KB，新体系明确要删）。
在那上面做功能等于给待拆的房子装修。

---

## 1. 判断依据：旧任务的文件归属

把 P1–P4 的写入范围按"新体系归属"分类：

| 写入路径 | 新体系归属 | 依据 |
|---|---|---|
| `tests/fixtures/sql/seed.sql` | → 评测仓 `environments/sql/` | 环境是 benchmark 资产（设计 §9.2 推荐 (a)） |
| `cloudagent_ext/diagnosis/cases/**` | → 评测仓 `datasets/golden/` | 数据集必须物理隔离（设计 §2.2） |
| `tests/diagnosis/test_case_meta.py` | → 评测仓 dataset manifest 校验 | 硬编码数字被内容哈希替代（设计 §4.3） |
| `tests/diagnosis/test_sql_seed_contract.py` | → 评测仓 `tests/` | 守的是环境契约 |
| `cloudagent_ext/diagnosis/switches.py` | ✅ **产品仓保留** | 机制开关是产品能力 |
| `cloudagent_ext/tool_system/tools/agent.py` | ✅ **产品仓保留** | 缺口注入是产品行为 |
| `cloudagent_ext/diagnosis/evaluation/runner.py` | ❌ **待删除** | 新体系删除整个 `evaluation/` |
| `cloudagent_ext/diagnosis/evaluation/scoring.py` | ❌ **待删除** | 评分逻辑迁移到评测仓 |
| `cloudagent_ext/diagnosis/evaluation/executors.py` | ⚠️ **迁移为 `eval_support/`** | 契约层保留在产品仓（设计 §2.1） |
| `cloudagent_ext/agent/registry.py`（F821） | ✅ **产品仓保留** | 与评测无关的既有缺陷 |
| `tests/diagnosis/test_session_wiring.py`（F821） | ✅ **产品仓保留** | 同上 |

**关键判据**：一个任务里同时写了"产品仓保留"和"待删除"的文件 → 必须拆，不能整包并入。

---

## 2. 逐任务评估

### P1 —— ✅ 全量并入，而且它是新体系的前提

**产物**（已核实）：

| 交付 | 内容 |
|---|---|
| `tests/fixtures/sql/seed.sql` | 98 行，幂等，`created_at` 固定基准，F1–F6 六条断言依赖事实 |
| 11 个 case JSON | `verification` runtime→static，`verified_against` 写依据不写数值 |
| `test_case_meta.py` | 锁死数字 17/15/6 → 28/4/6 |
| `test_sql_seed_contract.py` | 8 条静态守门，无 DSN 也能跑 |

**为什么必须并入**：新体系设计 §8 的 **P2 阶段（等价迁移）以"28/4/6 基线"为验收基准**。
P1 正好提供了这个基线：11 题 static + 每条 `verified_against` 都可复核。
不并入，新体系的等价性验证就没有参照物。

**为什么现在就该合并（而不是等评测仓建好再搬）**：
1. `main` 当前仍把 11 道**实际可核**的题标成 `runtime`——这是**不真实的元数据**，多挂一天多一天误导；
2. 这是已完成+已审查的工作，挂在分支上会腐烂（与 `main` 越离越远）；
3. 日后迁移只是 `git mv`，**历史与 blame 都保留**，不是重写。

**并入后的归属**：P1 产物在新体系里就是 `datasets/golden/` 的第一批内容 + 环境定义。
**不是废弃，是换仓库。**

**两个必须带过去的遗留问题**（ZCode 交接 §6 主动报告的，我确认属实）：

| 问题 | 处置 |
|---|---|
| ZCode 在审查送达前**把初版 seed 重放进了 `cloudagent_sim`**（含过宽的 GRANT + `ALTER DEFAULT PRIVILEGES`），缺陷 1 只约束"今后执行"，**不清历史残留** | 见下方 P0'（已实测确认残留内容） |
| `tenants/devices` 仍空 | 属 sync seed 职责，不在 P1 范围。但新体系生成 sql 题时会用到 `tenants`，需在环境层补齐 |

**P0' 的精确范围（2026-11-07 实测 `cloudagent_sim` 后修正）**：

我先按"授权全都要收"写，实测后发现要分开看：

```sql
-- ① 默认权限：这是真正的过宽，必须清
select * from pg_default_acl;
--   postgres | public | r | {cloudagent_ro=r/postgres}
--   → 今后任何人在 public 建表，只读角色自动可读
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM cloudagent_ro;

-- ② 表级 ACL：tenants/devices 的 SELECT 是产品必需的，不动
--   sync 域诊断要读这两张表（sync-004/005 依赖 devices）；
--   CLOUDAGENT_DB_QUERYABLE_TABLES = public.*
--   收掉会让 sync 域直接坏掉。只有 customers/orders 是 P1 seed 自己授的。
```

**所以 P0' 只做一件事：清 `pg_default_acl` 那一条。** 这比"清所有授权"小得多，
也避免了误伤 sync 域。这是我初稿判断过宽的地方，记录下来。

---

### P2 —— ⚠️ 拆分：产品半边留下，评测半边并入

**原写入范围拆开看**：

| 子任务 | 写哪里 | 判定 |
|---|---|---|
| T2.1 开关登记表 `switches.py` + `SwitchSpec` | 产品仓 | ✅ **照做**，与评测无关 |
| T2.1 `gap_injection_enabled()` 改走登记表 | 产品仓（`agent.py`） | ✅ **照做**。这是真 bug：现在写 `CLOUDAGENT_GAP_INJECTION=false` 仍会注入 |
| T2.2 "关掉 ⇒ 行为消失"守卫（compaction / invalidation / domain gate） | 产品仓测试 | ✅ **照做**。守的是产品机制 |
| T2.3 `runner.py` 泄漏守卫参数化 + `switch_guards` 字段 | ❌ 待删除文件 | ❌ **不做**。并入新体系 runner 的设计 |
| T2.3 `no_probe` 诚实标注 | 报告层 | ⚠️ 思路并入评测仓（新体系 report 层） |

**并入建议**：
- **P2 改名 P2a**，只保留产品侧（T2.1 + T2.2 中不碰 eval 的部分），**立即可做**，不再 blocked；
- **P2b**（runner 泄漏守卫）并入新体系设计 §6 的统计层 / §7 R1–R5 治理层——
  那本来就是"实验可信度"的一部分，不该单独存在。

**顺带一个发现**：`switches.py` 现在只有 3 个公开函数、无登记表，
而 `agent.py:182` 确实绕过了 `env_flag`。这条 bug 独立于评测体系，**建议尽快修**。

---

### P3 —— ❌ 不在产品仓实现

**原写入范围**：`evaluation/runner.py` + `tests/diagnosis/test_arm_presets.py` + `test_evaluation_runner.py`。
**三个文件全部在待删除 / 待迁移范围**。

**P3 的内容本身有价值**（`--set`、`--arm-from`、`arm_derivation`、
`single_variable` 字段、开关依赖表），但**实现目标要消失**。
把它做进 `runner.py` 就是给待拆的房子装修。

**处置**：把 P3 的**设计思路**并入新体系"实验层"——
新体系的 `runner/` 天然要读 `arm_env`，`--set`/`--arm-from` 语义与
`single_variable`/`declared_dependencies` 直接搬过去即可，代码按新骨架重写。

**当前不需要它**：阶段 5 的 live 对照本来就卡额度（`docs/needs-quota.md`），
新体系 P4（统计层）会一并覆盖多臂对比。**P3 作废，设计入档。**

---

### P4 —— ⚠️ 拆分：两行现在就做，其余迁走

**原写入范围拆开看**：

| 子任务 | 写哪里 | 判定 |
|---|---|---|
| T4.3 `agent/registry.py` F821（加 `Any` 导入） | 产品仓 | ✅ **立即做**（1 行） |
| T4.3 `test_session_wiring.py` F821（加 `pathlib`） | 产品仓测试 | ✅ **立即做**（1 行） |
| T4.1 `test_eval_bash_availability.py` | ❌ 评测测试 | ⚠️ 迁到评测仓或 `eval_support` 的测试 |
| T4.1 `executors.py` Bash 显式拒绝 | ⚠️ 迁到 `eval_support/` | 逻辑保留，位置变 |
| T4.2 `scoring.py` 截断判定 | ❌ 待删除 | 并入评测仓 scorer |

**关键判断**：T4.1 的 Bash 问题**是真的**（`dontAsk` 下 Bash 返回空串而非错误），
但它修的是**评测执行上下文**，而这个上下文在新体系里叫 `eval_support/execute.py`。
所以逻辑要留，位置要搬——**等新体系 P1 阶段（契约）一起做**，别在旧文件上改。

**F821 为什么现在做**：与评测无关，是 `ruff check` 红的唯一原因。
两行改动、零风险、立刻让 lint 清零。**这件事不该等评测体系。**

---

## 3. 修正后的工作包清单

| 新编号 | 内容 | 来源 | 状态 | 依赖 |
|---|---|---|---|---|
| **P1** | sql seed + 11 题 static | 原 P1 | **已完成待二审 → 合并** | — |
| **P0'** | 清 `cloudagent_sim` 的过宽授权残留 + `tenants` 补数 | 原 P1 遗留 | 可立即 | — |
| **P2a** | 产品侧开关登记表 + 机制守卫（不碰 eval） | 原 P2 的一半 | 可立即 | 无（解除 blocked） |
| **P4a** | 两处 F821 | 原 P4 的三分之一 | 可立即（1 行×2） | — |
| **EVAL-P0..P7** | 新评测体系全流程 | 新设计 | 待评审 | 决策已定 |

**作废 / 入档**：
- 原 P3（多臂预设）→ 设计思路入新体系实验层，不在产品仓实现
- 原 P2b（runner 泄漏守卫）→ 入新体系治理层
- 原 P4 的 Bash / 截断判定 → 等新体系 P1 契约阶段一起做

---

## 4. 建议的执行顺序

```
① 二审通过 P1 → 合并到 main（让 main 的 17/15/6 变成真的 28/4/6）
② 同时做 P4a（两行 F821）→ ruff 清零
③ 做 P0'（清 cloudagent_sim 授权残留）—— 小但必须，否则"只读角色"权限比声称的宽
④ P2a（产品开关 bug）—— 独立价值明确
⑤ 评测体系设计评审通过后，按 EVAL-P0..P7 推进
```

**②③④ 都是小时级，且互相独立**，可以在评测体系评审期间并行做完。
这样"评测体系"这个大工程就不会阻塞产品仓的既有缺陷修复。

---

## 5. 一个需要你注意的风险

原 P1–P4 的编号会和新体系的 `EVAL-P0..P7` 混淆。建议：
- 旧编号加前缀 **`LEGACY-`**（如 `LEGACY-P2`），或
- 直接用新表里的 **P1 / P0' / P2a / P4a**

我在任务板（`docs/collab/README.md`）里按第二种改。
