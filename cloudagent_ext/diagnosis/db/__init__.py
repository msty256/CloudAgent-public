#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""只读数据库访问子包（变更 add-sql-diagnostic-db-tools）。

组成与边界：

* ``sql_guard`` —— SQL 只读白名单校验（sqlglot AST，恰好一条纯查询）；
* ``connection`` —— DSN 加载（环境变量受控连接）/ 短连接只读会话 / 脱敏；
* ``postgres`` —— PostgreSQL 专属查询实现（未来 Database Adapter 的接缝）；
* ``tools`` —— ``get_schema`` / ``get_indexes`` / ``explain_sql``（build_tool
  工厂）与按需装配 ``register_sql_db_tools``。

依赖说明：本子包需要 ``db`` optional extra（``psycopg[binary]`` + ``sqlglot``，
安装方式 ``pip install -e ".[db]"``）。默认运行路径不导入本子包——未安装 extra
时仓库其余功能不受影响；只有显式装配（``register_sql_db_tools``）才会使用。
"""
