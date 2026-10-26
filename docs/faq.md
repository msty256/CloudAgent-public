# 常见问题

## 运行时报错

### `Rate limit exceeded. Please wait and retry.`

模型侧限流。常见于一条消息里并行派发多个子 Agent——每个子 Agent 都要额外一轮模型调用。

处理：
- 减少一次提问里的并行派发（把"全链路都查"拆成几个问题）
- 换一个限流更宽松的 Provider（`/model` 或改 `config.json`）
- 当前版本**不会自动退避重试**，连续失败请缩小范围后重试

### `DSN not configured (db_dsn_not_configured)`

没有配置数据库连接串。检查 `config.json` 的 `env` 段是否有 `CLOUDAGENT_DB_DSN`，
或当前 shell 是否设置了该环境变量。

> 注意：`.env` 文件不生效，只认 `config.json` 与环境变量。

### 日志检索全 0 命中

先确认根目录对不对：

```bash
echo $CLOUDAGENT_LOG_ROOT
ls $CLOUDAGENT_LOG_ROOT
```

最常见原因是 `CLOUDAGENT_LOG_ROOT` 指向了别的目录。**不要猜目录**——猜错会让你把"没查到"
误读成"没发生过"，这是诊断里最危险的错误。

### `protocol parse failed: ...`

子 Agent 返回的 JSON 不合法。常见原因是输出里的引号未转义（已在解析层做修复尝试）。

仍有问题时：
- 换一个更强的模型
- 缩小单次任务范围（让它少输出几个证据）
- 看 `eval/runs/<run_id>/cases/*.json` 里的原始文本

### 子 Agent 说 `(Agent completed with no output)`

子会话没有产出最终文本。通常是模型在工具调用中途被中断（超时 / 限流 / 上下文超限）。
换更小的任务重试；若是超时，调大 `--timeout-per-case`。

## 能力边界

### 为什么不能自动修复？

诊断结论本身可能错，而写操作不可逆。当前定位是**只诊断 + 给验证方案**：

```json
"recommendations": ["调整批次窗口或分批拉取"],
"validation_plan": ["重跑增量后核对 secondary.orders 行数"]
```

人工照这两项操作即可完成闭环。自动修复需要另一套有审批、能回滚的执行器，不在本仓库范围。

### 能接 MySQL / Kafka / Elasticsearch 吗？

- **MySQL**：暂不支持。只读 SQL 层是为 PostgreSQL 写的（`information_schema` 与 `EXPLAIN` 语法差异）。
  接入需要实现新的工具集。
- **Kafka**：不接原生 Admin API。消费位点信息当前通过日志与数据库表间接推断——
  这也是为什么"同步链路"以 Skill 而非独立子 Agent 的形式存在（见 [架构说明](architecture.md)）。
- **Elasticsearch / Loki**：同理，需要新的日志检索工具；现有日志工具只读文件系统。

### 能不能不用模型？

能跑的东西有两类：
- `pytest tests/diagnosis` —— 全部离线
- `runner --mode offline` —— 夹具回放，验证评测设施

但**诊断本身需要模型**：路由、取证策略、结论归纳都由模型完成。

### 数据会不会外发？

模型侧必然看到发出去的提示（含表结构、日志片段、代码片段）。除此之外没有第三方上报。
如果这不可接受，只能换成自建模型端点（`providers` 支持自定义 base_url）。

## 评测相关

### 离线评测 100% 通过，说明诊断很准吗？

**不说明。** 离线是夹具回放：回答是预先写好的，验证的是"评测设施能不能算对分"，
不验证"模型诊断得好不好"。真实结论只能看 `--mode live`。

### `n/a（分母 0）` 是什么意思？

该指标的分母样本数为 0——例如"可核验率"要求证据里含可抽取的关键词，
如果这批结果里一条都没有，就无法计算，显示 `n/a` 而不是 `0%`。
把 `n/a` 当 `0` 会让汇总失真，所以代码不做换算。

### 两套评分口径该看哪个？

`strict` 严格词匹配，反映"字面是否命中"；`calibrated` 做术语归一化与 Top-3 并集，
更接近人工判断。**两个都看**：差距大说明结论表述与基准用词不一致，而不是结论错。

## 其它

### `/tasks` 里的"缺口"是什么？

子 Agent 明确说"这条我没查到，但影响结论"的命题。下一轮派发会自动带上它，避免重复取证。
详见 [架构说明](architecture.md#缺口gap)。

### 为什么 `/tasks` 显示"结论冲突"却没有任何结论？

这是设计如此：两个子 Agent 给了相反判断，代码不替它们选边。
`/tasks` 只负责让你看见冲突，最终取舍由人或主 Agent 在报告里说明。
