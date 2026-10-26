#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""连接层：受控 DSN 加载 / 只读短连接会话 / 脱敏（决策 3/8）。

* **受控连接**：连接目标仅来自环境变量（``CLOUDAGENT_DB_DSN`` 为 primary，
  ``CLOUDAGENT_DB_DSN_SECONDARY`` 为 secondary）——工具输入只能选枚举
  ``target=primary|secondary``，不接受连接串 / 主机 / 凭证参数；
* **只读会话**：``default_transaction_read_only=on`` + ``statement_timeout``
  （5s）+ ``idle_in_transaction_session_timeout``；
* **短连接**：每次调用独立连接，``finally`` 释放（第一版不做连接池）；
* **脱敏**：所有错误信息经 :func:`redact_dsn` 打码，密码不落日志与输出。
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg

__all__ = [
    "DSN_ENV_VAR",
    "DSN_SECONDARY_ENV_VAR",
    "VALID_TARGETS",
    "CONNECT_TIMEOUT_S",
    "STATEMENT_TIMEOUT_MS",
    "DbConnectionError",
    "load_dsn",
    "resolve_dsn",
    "redact_dsn",
    "db_session",
]

DSN_ENV_VAR: str = "CLOUDAGENT_DB_DSN"
DSN_SECONDARY_ENV_VAR: str = "CLOUDAGENT_DB_DSN_SECONDARY"
# 工具输入只能选这两个枚举值；连接串本身永远来自环境变量。
VALID_TARGETS: tuple[str, ...] = ("primary", "secondary")
CONNECT_TIMEOUT_S: int = 10
STATEMENT_TIMEOUT_MS: int = 5000
_IDLE_TX_TIMEOUT_MS: int = 5000

_URI_PASSWORD_RE = re.compile(r"(://[^:/?#\s]+:)[^@/?#\s]+(@)")
_KV_PASSWORD_RE = re.compile(r"(password\s*=\s*)\S+", re.IGNORECASE)


class DbConnectionError(ValueError):
    """连接层结构化错误（配置缺失 / 连接不可用 / 会话设置失败）。"""


_DOC_HINT = "See docs/database-access.md for single/multi-database setup."


def resolve_dsn(target: str = "primary", env: dict[str, str] | None = None) -> str:
    """按 ``target`` 读取只读 DSN；缺失时给出配置指引（不读取任何工具输入）。

    * ``target`` 只接受 ``VALID_TARGETS`` 中的枚举值，其他值 → ``invalid_target``；
    * ``secondary`` 未配置时 → ``secondary_dsn_not_configured``，**绝不回退 primary**
      （静默回退会造成"以为查了下游、其实查了上游"的结论错误）。
    """

    if target not in VALID_TARGETS:
        raise DbConnectionError(
            f"invalid_target: {target!r} is not one of {list(VALID_TARGETS)}; "
            f"the connection string is never taken from tool input. {_DOC_HINT}"
        )
    source = env if env is not None else os.environ
    env_var = DSN_ENV_VAR if target == "primary" else DSN_SECONDARY_ENV_VAR
    dsn = str(source.get(env_var) or "").strip()
    if dsn:
        return dsn

    example = "postgresql://user:password@host:5432/dbname"
    config_snippet = '{"env": {"%s": "%s"}}' % (env_var, example)
    if target == "secondary":
        raise DbConnectionError(
            f"secondary_dsn_not_configured: {env_var} is not set; the tool will NOT fall "
            f"back to {DSN_ENV_VAR}. Configure it via the environment variable "
            f"(e.g. {env_var}={example}), or persistently in ~/.cloudagent/config.json "
            f'under the "env" block: {config_snippet}. {_DOC_HINT}'
        )
    raise DbConnectionError(
        f"{env_var} is not set. Configure the read-only PostgreSQL DSN via the "
        f"environment variable (e.g. {env_var}={example}), or persistently in "
        f'~/.cloudagent/config.json under the "env" block: {config_snippet}. {_DOC_HINT}'
    )


def load_dsn(env: dict[str, str] | None = None) -> str:
    """兼容入口：等价于 ``resolve_dsn("primary")``。"""

    return resolve_dsn("primary", env)


def redact_dsn(dsn: str) -> str:
    """移除 DSN 中的密码（URI 与 key=value 两种形式），用于错误信息与日志。"""
    if not isinstance(dsn, str):
        return "***"
    redacted = _URI_PASSWORD_RE.sub(r"\1***\2", dsn)
    redacted = _KV_PASSWORD_RE.sub(r"\1***", redacted)
    return redacted


@contextmanager
def db_session(dsn: str | None = None) -> Iterator[Any]:
    """只读短连接会话（上下文管理器；失败抛 :class:`DbConnectionError`）。"""
    resolved = dsn or load_dsn()
    try:
        conn = psycopg.connect(resolved, connect_timeout=CONNECT_TIMEOUT_S, autocommit=True)
    except psycopg.Error as exc:
        raise DbConnectionError(
            f"database unavailable: {exc} (dsn={redact_dsn(resolved)})"
        ) from exc
    try:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SET default_transaction_read_only = on")
                cursor.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
                cursor.execute(f"SET idle_in_transaction_session_timeout = {_IDLE_TX_TIMEOUT_MS}")
        except psycopg.Error as exc:
            raise DbConnectionError(
                f"failed to configure read-only session: {exc}"
            ) from exc
        yield conn
    finally:
        conn.close()
