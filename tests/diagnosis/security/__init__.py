#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""SQL 诊断安全对抗测试（变更 harden-sql-diagnostic-safety）。

集中入口说明与环境约定：

* 无 DSN 环境可运行（DB 相关断言仅检查"未被权限模式破坏"，不依赖真库）；
* 真库用例如需 DSN 沿用既有 skip 机制（tests/diagnosis/db/）；
* 真实模型对抗测试不纳入自动化（环境条件见变更 design）。

与既有用例的覆盖关系（复用 / 扩展 / 新增——禁止无意义重复）：

| 攻击面 | 既有覆盖（复用） | 本套件新增（差异面） |
|---|---|---|
| 多语句 / 非查询拒绝 | tests/diagnosis/db/test_sql_guard.py（11 用例） | 注释变体、多余分号、解析边界 |
| CTE / 嵌套边界 | 同上（写 CTE 拒绝） | 嵌套 WITH 内危险函数 |
| 危险函数 | ——（无） | test_sql_guard_adversarial（逐项 + 大小写 + pg_catalog 前缀） |
| SQL 注释注入 | ——（无） | test_prompt_injection（注释指令不改变校验） |
| 未授权工具调用 | 评测 safety 六规则（输出侧记录） | test_session_sandbox / test_prompt_injection（输入侧：执行边界拒绝） |
| 凭据读取（Bash） | 报告脱敏（test_connection + 评测） | test_session_sandbox（命令执行前拒绝） |
| 写/删命令（Bash） | 评测 safety 的 write_attempt 记录 | test_session_sandbox（执行前拒绝 + 副作用断言） |
| 非法参数 / 限额 | test_tools_offline（截断/参数面） | ——（复用） |
| 连接失败 / 超时 | test_db_tools_integration（需 DSN） | ——（复用） |
| 证据伪造 / 协议 | test_models / test_protocol（21 用例） | ——（复用） |
| 恶意案例 / 报告 | 评测 fixtures（sql-011 违规样本） | test_prompt_injection（注入文本响应判类安全） |
"""
