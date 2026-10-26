<div align="center">

# CloudAgent

**能自己查证据的研发排障 Agent**

用自然语言描述线上问题 · 自动派发只读子 Agent 取证 · 输出带证据与置信度的结论

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-3776AB?logo=python&logoColor=white)](#环境要求)
[![License](https://img.shields.io/badge/License-MIT-2ea44f)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-orange)](#项目状态)

</div>

---

## 这是什么

CloudAgent 是一个**命令行诊断工具**，也是一个**可复用的 Python Agent 运行时**。

它接收一句研发问题（"orders 为什么没同步到下游"），由一个主 Agent 拆成若干取证任务，
派给 **SQL / 日志 / 代码**三个只读子 Agent 去查库、翻日志、读代码，最后把结论按统一协议汇总，
**每条结论都关联具体证据**。

```
用户提问 ──▶ 主 Agent（规划 / 派发 / 汇总）
                 │
      ┌──────────┼──────────┐
      ▼          ▼          ▼
  sql-diagnosis log-diagnosis code-diagnosis
   只读 DB 查询    日志检索/时序    符号检索/调用链
      └──────────┼──────────┘
                 ▼
        统一协议：证据 · 根因 · 建议 · 验证方案 · 缺口
```

装完之后就是一条命令：

```bash
cloudagent -p "orders 上游 5 万行、下游 0 行，确认一下是不是真的没落库"
```

它不是一个通用聊天机器人，也不是运维平台。它只做一件事：**把"查证据"这件事自动化，并让结论可被复核**。

## 主要特性

| 特性 | 说明 |
|---|---|
| **只读取证** | 子 Agent 没有任何写入口：SQL 白名单 + 只读事务 + 只读账号三重防线，工具注册层再裁一次 |
| **结论必带证据** | 每条根因关联 `evidence_id`；证据带 `proves`（能证明什么）、`cannot_prove`（不能证明什么）、适用条件 |
| **不知道就说不知道** | 子 Agent 留下 `next_steps` / `limitations`，编排层收成"缺口"，下一轮带着它继续查 |
| **冲突不硬判** | 两个子 Agent 结论矛盾时并列呈现，不用代码替模型选边 |
| **可扩展** | 加工具、加子 Agent、加领域方法论（Skill）都是配置级改动；支持 Anthropic / OpenAI / GLM / DeepSeek 等 |
| **可度量** | 38 例带 Ground Truth 的案例库、离线与真实模型双模评测、双评分口径、跨域汇总 |

## 它解决什么问题

排障最耗时的不是"想不出原因"，而是**把散落在四个地方的事实拼起来**：
调度有没有跑、消息有没有消费、业务有没有处理成功、数据有没有真的落库。

大多数"AI 运维助手"止步于给建议：

> 建议您检查 Kafka 消费情况，确认消费者组是否正常。

CloudAgent 给的是这个：

```
orders 上游 50000 行、下游 0 行；tenant-003 增量任务 09:00 启动，
仅查询 orders 后 39 秒因批次窗口超时中止，位点未推进；下游表存在但为空。
→ 断点：调度窗口超时，未进入同步阶段（置信度 0.85，证据 4 条）
```

没查到的地方会明确写成"待验证"，而不是编一个听起来合理的答案。

## 快速开始

```bash
git clone https://github.com/msty256/CloudAgent-public.git && cd CloudAgent-public
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[db]"

cloudagent login                                  # 配置模型 API Key
cloudagent diag                                   # 自检：版本 / 配置 / 依赖
```

不需要数据库、不需要 API Key，先跑一次离线评测看看长什么样：

```bash
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync
```

要连库问真实问题（配置只读账号、日志目录）见 [安装与配置](docs/installation.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [安装与配置](docs/installation.md) | 环境要求、模型配置、只读数据库、日志目录 |
| [使用指南](docs/usage.md) | CLI / REPL、诊断流程、`/tasks` 解读、评测与报告 |
| [架构说明](docs/architecture.md) | 运行时分层、诊断链路、证据协议、缺口机制、扩展点 |
| [安全模型](docs/security.md) | 只读三重防线、权限模式、子 Agent 可见范围 |
| [常见问题](docs/faq.md) | 报错排查、能力边界、接入其它数据源 |

## 项目状态

**Alpha**（可跑通完整链路，接口仍可能变）。

已实现：单库/双库只读诊断、三个子 Agent、证据协议、缺口驱动编排、冲突检测、
离线与真实模型两套评测。

尚未实现：自动修复、Kafka 原生消费位点取证、MySQL 适配。

诊断质量仍在打磨：离线评测只验证评测设施本身，真实模型下的准确率尚未稳定，
**仓库中不宣称任何准确率指标**。

## 贡献

欢迎 Issue 与 PR。提交前请确认：

1. 新增能力附带测试；修复缺陷先补可复现用例
2. 不引入反向依赖（分层契约见 `pyproject.toml` 的 import-linter 配置）
3. 涉及权限、协议、工具注册的改动，需同步更新 `docs/` 对应章节

## 许可证

[MIT](LICENSE)。本项目包含由 [AgentSDK](https://gitcode.com/Ascend/AgentSDK)
（Copyright (c) 2026 Clawd Codex Team，MIT）衍生的代码，版权与许可全文见 [NOTICE](NOTICE)。
再分发时请同时保留 `LICENSE` 与 `NOTICE`。
