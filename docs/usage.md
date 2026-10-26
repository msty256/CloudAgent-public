# 使用指南

## 三种运行方式

```bash
cloudagent                        # 交互式 REPL
cloudagent -p "问题"               # 单次执行后退出
cloudagent diag                   # 安装自检（与 doctor 不是同一个命令）
cloudagent doctor                 # 环境与版本体检
```

## 交互式会话

```
❯ orders 为什么没同步到下游？

● 我会先确认调度是否触发，再核对消费与落库。派发日志取证。
  ⎿ [log-diagnosis] 检索调度日志 …
  ⎿ [log-diagnosis] tenant-003 增量任务 09:00 启动，39s 后超时中止
● 下游计数为 0，上游 50000。断点在调度窗口，未进入同步阶段。
```

| 斜杠命令 | 作用 |
|---|---|
| `/tasks` | 查看本次诊断：委派列表、失败原因、缺口、预算、注入次数、结论冲突 |
| `/model` | 查看 / 切换模型 |
| `/show <n>` | 查看第 n 条历史会话的完整 ID 与首条输入 |
| `/clear` | 清空当前上下文 |

### 怎么看 `/tasks`

```
诊断会话（request_id: 7f3a…）：
• [completed] log-diagnosis — 确认调度是否触发
• [completed] sql-diagnosis — 下游 orders 计数
已用 2/15 次委派
缺口（1 open / 0 blocked / 0 resolved）：
• [open] upstream orders 的确切行数未取到（复述 1 次）
结论冲突：0 处
```

- **委派**：谁被派出去、干什么、成没成
- **缺口**：子 Agent 明说"没查到但很重要"的命题；下一轮会自动带进提示
- **结论冲突**：两个子 Agent 给相反结论时出现，**不会被自动裁决**

## 一次诊断的推荐问法

| 场景 | 问法 | 会派给 |
|---|---|---|
| 数据没同步 | `orders 上游 5 万行、下游 0 行，帮我确认是不是真的没落库` | SQL |
| 接口报错 | `订单查询报 500，日志里有异常栈，先看是哪一步炸的` | 日志 |
| 死锁 / 并发 | `线索版本同步偶发死锁，怀疑 DELETE 和 MERGE 顺序不一致` | SQL + 代码 |
| 全链路 | `10-22 之后告警数据全停了，同步、消费、落库都可能有问题` | 日志 + SQL |

**问得越具体，派发越准**。一句"系统有问题"通常会被要求补充信息，而不是乱查一通。

## 评测

评测用来回答"诊断到底好不好"，而不是"能不能跑"。

```bash
# 离线：夹具回放，不连库、不调模型。验证的是评测设施本身
python -m cloudagent_ext.diagnosis.evaluation.runner --mode offline --domain sync

# 真实模型
python -m cloudagent_ext.diagnosis.evaluation.runner --mode live --domain sync

# 走真实派发链（主 Agent 决定派谁），而非直驱子 Agent
python -m cloudagent_ext.diagnosis.evaluation.runner --mode live --domain sync --dispatch main

# 路由评测：只判"该派谁"，不评价回答质量
python -m cloudagent_ext.diagnosis.evaluation.runner --mode live --routing

# 跨域汇总最近 8 次运行
python -m cloudagent_ext.diagnosis.evaluation.runner --summary --summary-last 8
```

| 参数 | 说明 |
|---|---|
| `--domain` | `sql` / `code` / `log` / `cross` / `sync` |
| `--cases` | 逗号分隔的 case_id 子集 |
| `--variant gaps-on\|gaps-off` | 是否启用缺口注入（对照实验用） |
| `--repeat N` | 同一轮内重复 N 次，取中位数 |
| `--max-cases N` | 只跑前 N 例，快速冒烟 |
| `--timeout-per-case N` | 单例超时秒数，默认 180 |

### 报告在哪

```
eval/runs/<run_id>/
├── summary.md      人读的汇总（指标 + 逐例结果）
├── run.json        机器读的完整数据
└── cases/*.json    逐例轨迹（含证据、根因、缺口）
```

指标口径：

| 指标 | 含义 |
|---|---|
| Top-1 | 首选根因命中 Ground Truth |
| 证据充分率 | 结论所需的证据是否齐备 |
| 可核验率 | 带可抽取关键词的证据占比（分母为 0 时显示 `n/a`） |
| 失败构成 | `parsed` / `invalid_output` / `crashed` / `grader_error` |

**两套评分口径**：`strict`（严格词匹配）与 `calibrated`（术语归一化 + Top-3 并集），并列输出，不互相替代。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CLOUDAGENT_DB_DSN` | — | 主库连接串 |
| `CLOUDAGENT_DB_DSN_SECONDARY` | — | 下游库连接串 |
| `CLOUDAGENT_DB_QUERYABLE_TABLES` | 全部 | 可查询表白名单 |
| `CLOUDAGENT_LOG_ROOT` | — | 日志根目录 |
| `CLOUDAGENT_CODE_ROOT` | 当前目录 | 代码检索根目录 |
| `CLOUDAGENT_GAP_INJECTION` | `on` | 是否把未解决缺口注入下一轮派发 |

## 退出码

| 码 | 含义 |
|---|---|
| `0` | 正常结束 |
| `1` | 运行错误（模型 / 数据库 / 配置） |
| `2` | 参数错误（如 `--routing` 未配 `--mode live`） |
