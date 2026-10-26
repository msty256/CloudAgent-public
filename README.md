<div align="center">

# CloudAgent

**能自己查证据的研发排障 Agent**

主 Agent 规划 · 三个只读子 Agent 取证 · 结论必须带证据

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-3776AB?logo=python&logoColor=white)](#环境要求)
[![License](https://img.shields.io/badge/License-MIT-2ea44f)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-orange)](#项目状态)

</div>

---

## 它解决什么问题

排障最耗时的不是"想不出原因"，而是**把散落在四个地方的事实拼起来**：
调度有没有跑、消息有没有消费、业务有没有处理成功、数据有没有真的落库。

大多数"AI 运维助手"止步于给建议：

> 建议您检查 Kafka 消费情况，确认消费者组是否正常。

CloudAgent 做的是另一件事——**自己去查，然后把证据摆出来**：

```
orders 上游 50000 行、下游 0 行；tenant-003 增量任务 09:00 启动，
仅查询 orders 后 39 秒因批次窗口超时中止，位点未推进；下游表存在但为空。
→ 断点：调度窗口超时，未进入同步阶段（置信度 0.85，证据 4 条）
```

结论里每句话都挂着证据，没查到的地方会明确写成"待验证"，而不是编一个听起来合理的答案。

## 两种用法

**当成一个排障工具**——装好、配好库和日志目录，直接问：

```bash
cloudagent -p "orders 为什么没同步到下游？"
```

**当成一个 Agent 运行时**——它本身是一套完整的 Python Agent 底座（工具系统、Skill 加载、
权限审批、会话与记忆、多 Provider），诊断能力只是长在上面的一层扩展。要接自己的工具和子 Agent：

```python
@AgentRegistry.register("my-diagnosis", tools=["Read", "Grep", "MyTool"], permission_mode="dontAsk")
def _prompt() -> str:
    return build_agent_prompt(identity=IDENTITY_CODE_REVIEWER, ...)
```

## 核心设计

```
                    ┌──────────────────────────────┐
   用户提问 ────────▶│  主 Agent（规划 / 派发 / 汇总）│
                    └──────────┬───────────────────┘
                               │ Agent 工具
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   sql-diagnosis        log-diagnosis        code-diagnosis
   只读 DB 工具          日志检索/时序分析       符号检索/调用链
          └────────────────────┼────────────────────┘
                               ▼
                    统一诊断协议（结构化 JSON）
                    证据 · 根因 · 建议 · 验证方案 · 缺口
```

四条不妥协的规则：

| 规则 | 为什么 |
|---|---|
| **子 Agent 只读** | 诊断结论可能错，写操作不可逆。三层防护（SQL 白名单 / 只读事务 / 只读账号）在代码与数据库侧强制 |
| **结论必须带证据** | 每条根因关联 `evidence_id`；禁止把"静态风险"说成"已发生的故障" |
| **不知道就说不知道** | 结果里有 `limitations` 与 `next_steps`，编排层会把它们变成下一轮的取证任务 |
| **冲突不硬判** | 两个子 Agent 结论矛盾时并列呈现，不用代码替模型选边 |

## 快速开始

```bash
git clone https://github.com/<you>/CloudAgent.git && cd CloudAgent
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[db]"

cloudagent login                                  # 配置模型 API Key
cloudagent diag                                   # 自检：版本 / 配置 / 依赖
```

跑一次不需要任何外部依赖的离线评测：

```bash
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync
```

要连库问真实问题，见 [安装与配置](docs/installation.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [安装与配置](docs/installation.md) | 环境要求、模型配置、只读数据库、日志目录 |
| [使用指南](docs/usage.md) | CLI / REPL、诊断流程、评测与报告 |
| [架构说明](docs/architecture.md) | 运行时分层、诊断链路、证据协议、缺口机制 |
| [安全模型](docs/security.md) | 只读三重防线、权限模式、子 Agent 可见范围 |
| [常见问题](docs/faq.md) | 报错排查、能力边界、接入其它数据源 |

## 项目状态

**Alpha**。已实现并测试的是：单库/双库只读诊断、三个子 Agent、证据协议、缺口驱动编排、
离线与真实模型两种评测模式。**尚未实现**：自动修复、Kafka 原生消费位点取证、MySQL 适配。

诊断质量仍在打磨：离线评测只验证评测设施本身，真实模型下的准确率数据尚未稳定，仓库中不宣称任何准确率指标。

## 贡献

欢迎 Issue 与 PR。提交前请确认：

1. 新增能力附带测试；修复缺陷先补可复现用例
2. 不引入反向依赖（分层契约见 `pyproject.toml` 的 import-linter 配置）
3. 涉及权限、协议、工具注册的改动，需同步更新 `docs/` 对应章节

## 许可证

[MIT](LICENSE)。本项目包含由 [AgentSDK](https://gitcode.com/Ascend/AgentSDK)
（Copyright (c) 2026 Clawd Codex Team，MIT）衍生的代码，版权与许可全文见 [NOTICE](NOTICE)。
再分发时请同时保留 `LICENSE` 与 `NOTICE`。
