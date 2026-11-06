# 协作任务板

> 更新：2026-11-07 · 维护：DSH Lead
> 契约与目录约定见仓库根 [`AGENTS.md`](../../AGENTS.md)。

## 当前状态

| 工作包 | 标题 | 状态 | 负责人 | 分支 | 设计 | 审查 |
|---|---|---|---|---|---|---|
| **P1** | sql 域取证基线：11 题 `runtime → static` | `ready` | ZCode | `feat/p1-sql-seed` | [design/p1](design/p1-sql-seed.md) | 待 |
| **P2** | 开关泄漏守卫泛化 | `blocked`（待 P1 合并） | ZCode | `feat/p2-switch-guard` | [design/p2](design/p2-switch-guard.md) | 待 |
| **P3** | 多臂预设：`variant` 只是预设，开关独立 | `blocked_by: P2` | ZCode | `feat/p3-arm-presets` | [design/p3](design/p3-arm-presets.md) | 待 |
| **P4** | 评测链路缺陷收口（Bash 空返回 / unfinished 归类） | `ready` | ZCode | `feat/p4-eval-chain` | [design/p4](design/p4-eval-chain.md) | 待 |

状态词：`ready`（可开工）/ `in_progress` / `in_review` / `changes_requested` / `done` / `blocked`。

## 为什么是这个顺序

1. **P1 排第一**：它不烧模型额度，却把"可核题"从 17 提到 28 —— 所有后续 live 对照的分母。
   而且我刚实测确认**数据已经在本机库里**，真正缺的是"仓库内可复现的 seed + 可执行的断言测试"。
2. **P2 → P3 必须串行**：P3 的多臂预设要依赖 P2 的守卫表，否则新臂一样是"声明关了但没关"。
3. **P4 独立**：它修的是评测链路自身缺陷（见 `docs/baseline-attempt-2026-11-03.md` §5.1、§7），
   不修的话任何 live 结论都可能是"链路坏了"而不是"模型不行"。

## 本仓不做的（已明确排除）

- 阶段 5 的 live 分臂对照（卡额度，见 `docs/needs-quota.md` §2）
- cross 域 6 题的 Java 样本项目（仓库外项目，提示词已写好）
- 阶段 6（E 经验沉淀 / F 记忆自评）

## 交接与审查记录

| 日期 | 工作包 | 类型 | 文件 |
|---|---|---|---|
| 2026-11-07 | — | 基线 | [baseline-2026-11-07.md](baseline-2026-11-07.md) |
