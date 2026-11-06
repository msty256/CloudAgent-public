# AGENTS.md — CloudAgent 双 Agent 协作契约

> 本文件是 **ZCode（开发）** 与 **DSH Lead（设计 / 审查）** 之间的共同契约。
> ZCode 工作区指令文件的读取顺序是 `<repo>/AGENTS.md`（本文件），
> 所以**动手前先读完这一节，再读它指向的任务卡**。

---

## 0. 角色与所有权

| 角色 | 谁 | 职责 | 可以写的地方 |
|---|---|---|---|
| **设计 + 审查** | DSH Lead | 定规格、定验收标准、审实现、跑闸门、判"过 / 打回" | `docs/design/**`、`docs/collab/reviews/**`、`AGENTS.md` |
| **开发** | ZCode | 按任务卡实现、补测试、自测、写交接说明、提交 | `cloudagent_ext/**`、`tests/**`、`scripts/**`、`docs/collab/handoffs/**` |

**硬规则**

1. 设计文档（`docs/design/**`、`docs/proposals/**`、`docs/diagnosis-redesign.md`）**只读**：
   发现规格有问题 → 不直接改，写进交接说明的「规格疑问」小节，由 Lead 裁决。
2. 开发代码（`cloudagent_ext/**`、`tests/**`）**只有 ZCode 写**。Lead 只在打回时写审查意见，不代改。
3. 一个任务卡一个分支。分支名 `feat/<task-id>-<slug>`，例：`feat/p1-sql-seed`。
4. **不要动 `~/.cloudagent/`**（仓库外本机配置，含凭据）。需要环境变量时用 `task` 里给的方式注入。

---

## 1. 共同工作目录与分类

仓库根 = `C:\Users\Administrator\Desktop\CloudAgent-public`（下称 `<repo>`）。
**唯一新增的协作目录是 `docs/collab/`**，其余沿用仓库既有分层。

```
<repo>/
├── AGENTS.md                     ← 本文件（契约，唯一入口）
├── docs/
│   ├── collab/                   ← 【协作区】所有跨角色产物都在这里
│   │   ├── README.md             ← 任务板：谁在做、到哪一步、下一步
│   │   ├── baseline-2026-11-07.md← 环境与测试基线（动手前必读，避免重复踩坑）
│   │   ├── design/               ← 【设计区】Lead 写，ZCode 只读
│   │   │   └── pX-*.md           ← 每个工作包一份实施规格 + 验收标准
│   │   ├── tasks/                ← 【任务卡】一卡一文件，状态写在卡头
│   │   │   └── pX-*.md
│   │   ├── handoffs/             ← 【交接区】ZCode 写完活在这里留说明
│   │   └── reviews/              ← 【审查区】Lead 写审查结论（过 / 打回 + 缺陷清单）
│   ├── proposals/                ← 只读：阶段提案（历史决策）
│   ├── diagnosis-redesign.md     ← 只读：改造总纲
│   ├── needs-quota.md            ← 只读：卡在额度/环境的事
│   └── case-audit-2026-11-01.md  ← 只读：案例库体检
├── cloudagent_ext/               ← 【开发区】代码
│   └── diagnosis/
│       ├── cases/{code,sql,log,cross,sync}/*.json   ← 案例 gt（改动需同步锁死数字）
│       └── db/                   ← SQL 域工具与安全护栏
├── tests/                        ← 【开发区】测试
│   └── fixtures/sql/             ← seed 脚本落点（见 P1）
└── .cloudagent/ .workbuddy/ .reports/ .idea/  ← 本地状态，已被 .gitignore 忽略，别提交
```

### 1.1 分类口径（写进任何文档前先对齐）

| 分类 | 判定 | 例 |
|---|---|---|
| **机制保证** | 改完 + 对应测试全绿即可宣称 | `blocked_only` 生效、陈旧写入归零、seed 幂等 |
| **统计效果** | 必须等 live 对照数据，样本 <30 只能描述不能推断 | "诊断成功率提升 X%" |
| **不可宣称** | 论文/帖子的数字、无对照的机制收益 | 82.6% / 87.19% |

任何产出里出现效果数字，必须标注它属于哪一类。**没有对照数据的"提升"一律不写。**

---

## 2. 工作包与顺序

任务卡的**唯一来源**是 `docs/collab/tasks/`，任务板汇总在 `docs/collab/README.md`。
当前排定（详见任务板）：

| 工作包 | 内容 | 是否烧模型额度 | 依赖 |
|---|---|---|---|
| **P1** | sql 域 seed：14 题 `runtime → static` | 否 | 本机 PG 5433（已验证可写） |
| **P2** | 开关泄漏守卫泛化（每个机制开关都要"声明关了→验证真关了"） | 否 | — |
| **P3** | 阶段 5 多臂预设：`variant` 只是预设，开关独立 | 否 | P2 |
| **P4** | 评测链路缺陷收口：`Bash` 返回空、`unfinished` 单独归类 | 否 | — |

**顺序约束**（来自 `docs/diagnosis-redesign.md` §5.1，不可破）：
P1 可并行；P2 → P3 必须串行；P4 独立。**任何工作包都不许动 live 评测的开关默认值。**

---

## 3. ZCode 的开发流程（每个工作包照做）

1. **读**：本文件 → `docs/collab/README.md` → 对应 `design/` 规格 → 对应 `tasks/` 卡。
2. **认领**：把任务卡头部状态改成 `in_progress`，写上开始时间与分支名，**先提交这一次状态变更**。
3. **开工前自检**：跑一遍 `docs/collab/baseline-2026-11-07.md` 里的「本地基线快照」命令，
   确认自己的起点与基线一致（不一致先在交接说明里报，不要默默修）。
4. **实现**：只动任务卡 `写入范围` 列出的路径；越界先在卡里改范围并说明理由。
5. **自测**：跑任务卡 `验收命令` 全部通过，外加 `ruff check` 无新增错误。
6. **交接**：写 `docs/collab/handoffs/<task-id>.md`，含：改了什么、为什么这么改、
   取舍与被否方案、新增/改了哪些测试、**还没做的事**、规格疑问。
7. **提交**：一次逻辑改动一个 commit，信息用 `feat(p1): …` / `fix(p2): …` / `test(p1): …`。
   提交前 `git status` 必须干净说明（不许混入 `.idea/`、`__pycache__/`、`eval/runs/`）。

---

## 4. Lead 的审查流程（每个工作包照做）

1. 读 handoff + `git diff main...<branch>`；
2. 核对**规格符合度**：任务卡的验收标准逐条对；
3. 跑闸门：验收命令 + `pytest tests/diagnosis`（基线 828 passed / 24 skipped）
   + `pytest tests/context`（165 passed）+ `ruff check <改动文件>`；
4. 检查**测试是否真的守住了机制**（反向条件、关闭开关后行为确实消失，不是只断言变量读到了）；
5. 结论写 `docs/collab/reviews/<task-id>.md`：`PASS` 或 `CHANGES_REQUESTED` + 逐条缺陷（含复现方式）。

**打回标准（任一条命中即打回）**：
- 验收命令没跑通却声称通过；
- 新增行为没有对应测试，或测试只覆盖"happy path"；
- 改了锁死数字（`test_case_meta.py` 的 17/15/6）却没有同步更新 schema/文档；
- 引入反向依赖（`pyproject.toml` 的 import-linter 契约）；
- 在文档里写了"统计效果"却没有对照数据。

---

## 5. 环境事实（2026-11-07 已实测，别再重新发现）

| 事实 | 值 / 说明 |
|---|---|
| Python | `D:\python312\python.exe`，3.12.10，**无 venv**，`cloudagent_ext` 从仓库根直接导入 |
| 可选依赖缺失 | `textual` / `pathspec` / `argcomplete` 未装 → `tests/cli` 6 失败、`tests/skills` 6 失败，**属环境缺失，不是代码缺陷** |
| PostgreSQL | `cloudagent-postgres` 服务（PG16），**127.0.0.1:5433** 可连；库 `cloudagent_sim`（上游）+ `cloudagent_sim_downstream`（下游） |
| PG 数据现状 | `orders` 50000、`customers` 2000、`devices` 50、`tenants` **0（空）**；索引只有 4 个主键 + `idx_customers_region` |
| PG 凭据 | 本机 `~/.cloudagent/db_sim.env`（**仓库外，绝不复制进仓库**）：RO 密码给只读校验，super 密码给 seed |
| 日志仿真实体 | `~/.cloudagent/config.json` 的 `CLOUDAGENT_LOG_ROOT` 指向 `C:\Users\Administrator\Desktop\cloudAgent\logs-sim` |
| 测试基线 | `tests/diagnosis` 828 passed / 24 skipped；`tests/context` 165 passed；`tests/tool_system` 115 passed |
| ruff 已知残留 | 3 处 F821：`cloudagent_ext/agent/registry.py:159`（`Any` 未导入）、`tests/diagnosis/test_session_wiring.py:685`（`pathlib` 未导入，2 处） |
| 模型额度 | **不要尝试 live 评测**（见 `docs/needs-quota.md`）；所有工作包都是离线可完成的 |

---

## 6. 禁止事项

- 不许把 `~/.cloudagent/db_sim.env` 的内容、DSN、密码写进仓库任何文件（含测试、日志、handoff）。
- 不许为了让测试变绿而放宽断言或删用例；确实要改用例必须在 handoff 里单列「为什么这条契约变了」。
- 不许改 38 题案例库里 `ground_truth` 的语义而不同时更新 `verified_against`。
- 不许跑真实模型评测来"验证一下"（烧额度，且会污染基线）。
