# 协作任务板

> 更新：2026-11-07 · 维护：DSH Lead
> 契约与目录约定见仓库根 [`AGENTS.md`](../../AGENTS.md)。

## 当前状态

> **2026-11-07 重排**：新评测体系立项（[design/eval-system-design.md](design/eval-system-design.md)）后，
> 原 P1–P4 已按**文件归属**重新划分，依据见
> [design/p1-p4-vs-eval-system.md](design/p1-p4-vs-eval-system.md)。

### 执行顺序（依次做，前两项可并行）

| 序 | 工作包 | 标题 | 状态 | 负责人 | 仓库 | 设计与审查 |
|---|---|---|---|---|---|---|
| **1** | **P1** | sql 域取证基线：11 题 `runtime → static` | **`PASS` 待合并** | ZCode | 产品仓 | [design](design/p1-sql-seed.md) · [二审 PASS](reviews/p1-round2.md) |
| **2** | **P4a** | 清掉两处 ruff F821（**15 分钟**） | `ready` | ZCode | 产品仓 | [任务卡](tasks/p4a-f821.md) |
| **3** | **P0'** | 清 `cloudagent_sim` 的 `pg_default_acl` 残留（**20 分钟**） | `ready` | ZCode | 只动数据库 | [任务卡](tasks/p0-prime-acl-cleanup.md) |
| **4** | **P2a** | 开关登记表 + 机制守卫（**产品侧**） | `ready` | ZCode | 产品仓 | [design](design/p2a-switch-registry.md) · [任务卡](tasks/p2a-switch-registry.md) |

### 评测体系（决策已定，按序推进）

| 序 | 工作包 | 标题 | 状态 | 仓库 | 设计 / 任务卡 | 预估 |
|---|---|---|---|---|---|---|
| **E0** | **EVAL-P0** | 还清产品→评测反向依赖（`redact_sensitive` 迁 utils） | `ready` | 产品仓 | [任务卡](tasks/eval-p0-redaction.md) | 30 min |
| **E1a** | **EVAL-P1a** | RunRecord 契约 + `eval-run` 子命令 | `ready`（依赖 E0） | 产品仓 | [design §3](design/eval-system-design.md) · [任务卡](tasks/eval-p1a-runrecord.md) | 1 天 |
| **E1b** | **EVAL-P1b** | 评测仓骨架 + RunRecord 消费 | `ready`（依赖 E1a） | **评测仓（新建）** | [任务卡](tasks/eval-p1b-repo-skeleton.md) | 1 天 |
| **E2** | **EVAL-P2** | 等价迁移（历史 run + 38 题 + 删产品评测代码） | `ready`（依赖 E1a/E1b） | 两仓 | [任务卡](tasks/eval-p2-migration.md) | 2 天 |
| E3 | EVAL-P3 | 修评分口径（别名组 / kind 拆分 / 分层） | 待 E2 | 评测仓 | [design §5](design/eval-system-design.md) | 1 天 |
| E4 | EVAL-P4 | 统计层（Wilson CI / pass^k / 两臂对比） | 待 E2 | 评测仓 | [design §6](design/eval-system-design.md) | 1 天 |
| E5 | EVAL-P5 | 生成器 PoC（sql 单域） | 待 E3/E4 | 评测仓 | [design §4](design/eval-system-design.md) | 3–5 天 |
| E6 | EVAL-P6 | 治理层（冻结 / canary / 预算门限 / CI） | 待 E4 | 评测仓 | [design §7](design/eval-system-design.md) | 1 天 |
| E7 | EVAL-P7 | 扩域（log → code → cross） | 待 E5 | 评测仓 | [design §4](design/eval-system-design.md) | 大 |

**已定决策**（见 [design §11](design/eval-system-design.md#11-决策记录2026-11-07-全部落定)）：
评测仓**拥有环境定义** · 评测仓**私有** · 本地路径 `C:\Users\Administrator\Desktop\cloudagent-eval`

**为什么 E0→E2 必须先做**：E2 的等价性验证是后面所有改进的信任基础。
跳过它直接改口径，将来分数变化就分不清是"改进了"还是"搬坏了"。

### 作废 / 并入（设计入档，代码不写）

| 原任务 | 去向 |
|---|---|
| **P3** 多臂预设 | ❌ **作废**。目标文件 `evaluation/runner.py` 在新体系里删除。设计思路并入新体系实验层 |
| **P2b** runner 泄漏守卫 | ➡️ 并入新体系治理层（§7 R1–R5） |
| **P4 其余**（Bash 空返回） | ➡️ **延后到 EVAL-P3**。在 [EVAL-P1a 任务卡](tasks/eval-p1a-runrecord.md) 里登记为 `KNOWN-ISSUE(eval-bash-empty)`，P3 修评分口径时一并处理 |
| **P4 其余**（截断判定） | ➡️ 并入 EVAL-P3（评分层的 `unfinished` / `invalid_output` 分界） |

状态词：`ready`（可开工）/ `in_progress` / `in_review` / `changes_requested` / `PASS`（审查通过待合并）/ `done` / `blocked` / `superseded`（作废）。

## 合并前必读

P1 合并到 `main` 前，先处理本目录下**未提交的文档改动**
（`docs/collab/**` 有 8 个新文件 + 4 个改动），避免文档混入 P1 的合并提交。

## 派工方式（重要）

**任务由人（项目所有者在 ZCode 对话里）转达，Lead 不直接给 ZCode 发消息。**
所以本目录里的任务卡必须是**自包含**的：ZCode 只需要读三个文件就能开工——

```
AGENTS.md  →  docs/collab/README.md（本文件）  →  docs/collab/tasks/<id>.md
                                                ↘ docs/collab/design/<id>.md
```

凡是"要口头补充才能开工"的内容都算任务卡缺陷，发现后由 Lead 补进任务卡。

## 基准目录（必须先对齐）

ZCode 之前工作在 **`D:\cloudAgent`**（私有旧仓，HEAD `e73e5f7`，仅 sql 域 14 题）。
本协作的基准是**当前仓库**：

```
C:\Users\Administrator\Desktop\CloudAgent-public   （HEAD 见下，38 题案例库）
```

两者差异不是"版本新一点"，而是**案例库规模与已合入机制都不同**：
`CloudAgent-public` 含 code/log/cross/sync 四域共 38 题，且阶段 3（上下文压缩）
与阶段 4（证据失效传播）已合入。**在 `D:\cloudAgent` 上做的实现不能直接搬过来。**

## 为什么是这个顺序

1. **P1 排第一**：它不烧模型额度，却把"可核题"从 17 提到 28 —— 所有后续 live 对照的分母。
   已完成并通过二审，是**待合并**状态。
2. **P4a / P0' 排第二三**：都是小时级、互不依赖、且**与评测体系无关**——
   `ruff` 现在有 3 个 error 一直红着，数据库有一条隐式默认授权一直生效。
   这类小债不该被"评测体系大工程"阻塞。
3. **P2a 排第四**：它修的是**产品真 bug**（`CLOUDAGENT_GAP_INJECTION=false` 关不掉注入），
   独立于评测体系，所以从原 `blocked` 解除了。
4. **评测体系排最后**：它是独立仓的大工程，且需要设计评审。
   但它不阻塞上面三件事——这是本次重排的核心目的。

## 本仓不做的（已明确排除）

- 阶段 5 的 live 分臂对照（卡额度，见 `docs/needs-quota.md` §2）
- cross 域 6 题的 Java 样本项目（仓库外项目，提示词已写好）
- 阶段 6（E 经验沉淀 / F 记忆自评）

## 交接与审查记录

| 日期 | 工作包 | 类型 | 文件 |
|---|---|---|---|
| 2026-11-07 | — | 基线 | [baseline-2026-11-07.md](baseline-2026-11-07.md) |
