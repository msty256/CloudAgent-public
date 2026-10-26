# 编排器命令速查

> 所有命令的前缀为 `cloudagent orchestrator`。按场景分类。
>
> ℹ️ **本速查表中的命令是正确、可信的，可直接使用。** 仅当对某个子命令的具体参数/用法拿不准时，再用 `-h` 查询核实：
>
> - 顶层：`cloudagent orchestrator -h`
> - 子命令：`cloudagent orchestrator <command> -h`（如 `cloudagent orchestrator issue -h`、`cloudagent orchestrator issue retry -h`）
>
> 无需每次执行前都跑 `-h`——那样太慢。速查表已覆盖常用场景，正常执行即可。

## 前置准备

如果用户使用了虚拟环境，在执行编排器命令前先激活：

```bash
cd /path/to/project
source .venv/bin/activate
cloudagent orchestrator server status
```

也可以直接使用虚拟环境内的 cli，无需手动 activate：

```bash
cd /path/to/project && .venv/bin/cloudagent orchestrator server status
```

**注意**：虚拟环境不是必须的。如果未使用虚拟环境，直接执行 `cloudagent` 即可。

## 守护进程管理

> `server start` 是长驻前台进程，直接运行会阻塞当前 shell。需后台运行（`nohup ... &` 或 `... &`）否则命令无法返回。

```bash
# 启动（后台运行，日志重定向）
nohup cloudagent orchestrator server start --workflow ./workflow.md > /tmp/orchestrator.log 2>&1 &
cloudagent orchestrator server start --workflow ./workflow.md --gateway           # 带 IM 网关
cloudagent orchestrator server start --workflow ./workflow.md --workflow-yaml ./.cloudagent/workflow.yaml

# 查看状态
cloudagent orchestrator server status

# 停止
cloudagent orchestrator server stop --all
cloudagent orchestrator server stop --workspace /tmp/workspaces
```

## Issue 管理

```bash
# 列表与详情
cloudagent orchestrator issue list                                          # 所有 Issue
cloudagent orchestrator issue list --status running                         # 筛选
cloudagent orchestrator issue show --id <issue-id>                          # 详情

# 跟踪
cloudagent orchestrator issue tail --id <issue-id>                          # 实时跟踪
cloudagent orchestrator issue tail --id <issue-id> --turn 5                 # 特定 turn
cloudagent orchestrator issue transcript --id <issue-id>                    # 完整对话
cloudagent orchestrator issue transcript --id <issue-id> --role assistant   # 仅 assistant
cloudagent orchestrator issue diff --id <issue-id>                          # 代码变更
cloudagent orchestrator issue diff --id <issue-id> --full                   # 完整 diff

# 控制
cloudagent orchestrator issue stop --id <issue-id>                          # 终止
cloudagent orchestrator issue pause --id <issue-id> --reason "..."          # 暂停
cloudagent orchestrator issue resume --id <issue-id>                        # 恢复
cloudagent orchestrator issue retry --id <issue-id> --mode reset            # 重置重试
cloudagent orchestrator issue retry --id <issue-id> --mode followup         # 追加 commit
cloudagent orchestrator issue retry --id <issue-id> --mode unblock          # 解封
cloudagent orchestrator issue retry --id <issue-id> --mode reset --force    # 强制重试
cloudagent orchestrator issue rebase --id <issue-id>                        # 变基
cloudagent orchestrator issue rebase --id <issue-id> --force                # 强制变基

# 注入与控制
cloudagent orchestrator issue inject --id <issue-id> "提示内容"              # 注入提示
cloudagent orchestrator issue inject --id <issue-id> --list                 # 列出提示
cloudagent orchestrator issue inject --id <issue-id> --remove 1             # 删除提示
cloudagent orchestrator issue attach --id <issue-id>                        # 实时 TUI 连接
cloudagent orchestrator issue takeover --id <issue-id>                      # 接管为交互式 REPL
cloudagent orchestrator issue resume-session --id <issue-id>                # 恢复 LLM 上下文

# 澄清
cloudagent orchestrator issue clarify --id <issue-id> --answer "..."        # 回答澄清
cloudagent orchestrator issue clarify --id <issue-id> --forward-to-author   # 转发给作者
cloudagent orchestrator issue clarify --id <issue-id> --resolve             # 标记已解决
cloudagent orchestrator issue clarify --id <issue-id> --recheck             # 重新分析

# 审查反馈
cloudagent orchestrator issue feedback --id <issue-id> --list               # 列出待处理反馈
cloudagent orchestrator issue feedback --id <issue-id> --approve            # 批准
cloudagent orchestrator issue feedback --id <issue-id> --dismiss            # 驳回
cloudagent orchestrator issue review --id <issue-id> --approve              # 审查批准
cloudagent orchestrator issue review --id <issue-id> --reject --feedback "..."  # 审查驳回

# 工作区文件
cloudagent orchestrator issue workspace --id <issue-id> --ls                # 文件列表
cloudagent orchestrator issue workspace --id <issue-id> --cat <file>        # 查看文件
cloudagent orchestrator issue workspace --id <issue-id> --edit <file> --with "..."  # 编辑文件

# 初始化
cloudagent orchestrator issue init                                           # 交互式创建 Issue 卡片
cloudagent orchestrator issue init --id F-37.1 --title "..." --non-interactive  # 非交互式
```

## 工作流管理

```bash
cloudagent orchestrator workflow init                                        # 初始化 workflow.md
cloudagent orchestrator workflow init --template workflow-local              # 本地跟踪器模板
cloudagent orchestrator workflow init --non-interactive                      # 非交互式
cloudagent orchestrator workflow list-templates                              # 列出可用模板
```

## 工作区管理

```bash
cloudagent orchestrator workspace list                                       # 列出保留的工作区
cloudagent orchestrator workspace list --status completed                    # 筛选
cloudagent orchestrator workspace show --id <issue-id>                       # 详情
cloudagent orchestrator workspace cd --id <issue-id>                         # 输出路径
cloudagent orchestrator workspace cleanup --id <issue-id>                    # 清理单个
cloudagent orchestrator workspace cleanup --all-completed                    # 清理所有已完成
cloudagent orchestrator workspace cleanup --all-completed --force            # 跳过确认
cloudagent orchestrator workspace verify --id <issue-id>                     # 运行验证
```

## 规则管理

```bash
cloudagent orchestrator rules list                                           # 列出所有规则
cloudagent orchestrator rules review --id 1                                  # 查看规则详情
cloudagent orchestrator rules delete --id 1                                  # 删除规则
cloudagent orchestrator rules extract                                        # 提取规则
cloudagent orchestrator rules extract --dry-run                              # 预览模式
cloudagent orchestrator rules extract --limit 5                              # 限制处理数量
cloudagent orchestrator rules stats                                          # 规则统计
```

## 仪表盘

```bash
cloudagent orchestrator dashboard                                            # 启动 Web 仪表盘
cloudagent orchestrator dashboard --port 8080                                # 指定端口
```

## IM 网关

```bash
cloudagent orchestrator server connect-gateway    # 连接 IM 网关
cloudagent orchestrator server disconnect-gateway  # 断开 IM 网关
```
