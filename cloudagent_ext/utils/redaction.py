#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""通用文本脱敏（DSN / 密码 / API Key / 手机号 / 邮箱）。

**为什么在 utils 而不是 evaluation**：日志工具（产品）与评测报告（评测）
共用同一套脱敏规则，避免规则漂移。原实现在
``diagnosis/evaluation/report.py``，属分层倒置（产品 import 评测），
EVAL-P0（2026-11-07）迁到此处。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["redact_sensitive", "redact_payload"]

_DSN_PATTERN = re.compile(r"postgresql://[^\s\"'<>]+")
_PASSWORD_ASSIGN = re.compile(r"(?i)(password|passwd|pwd|api[_-]?key|token)\s*[=:]\s*([^\s,;\"']+)")
_KEY_PREFIX = re.compile(r"\b(sk-[A-Za-z0-9_-]{6,}|ms-[0-9a-f-]{8,})\b")
# P3.3（add-log-analysis-domain）：日志域脱敏扩展——手机号 / 邮箱（工具与报告共用）
_PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _redact_dsn(match: re.Match[str]) -> str:
    url = match.group(0)
    if "***" in url:  # 已脱敏形态保持原样
        return url
    return re.sub(r"://([^:@/]+):([^@/]+)@", r"://\1:***@", url)


def redact_sensitive(text: str) -> str:
    """抹除文本中的 DSN 凭据 / 密码赋值 / 疑似 API Key / 手机号 / 邮箱。

    P3.3（add-log-analysis-domain）：扩展手机号与邮箱规则——日志工具输出与
    评测报告**共用同一函数**，避免脱敏规则在工具层与评分层漂移。
    """

    if not text:
        return text
    text = _DSN_PATTERN.sub(_redact_dsn, text)
    text = _PASSWORD_ASSIGN.sub(lambda m: f"{m.group(1)}=***", text)
    text = _KEY_PREFIX.sub("***", text)
    text = _PHONE_PATTERN.sub("1**********", text)
    text = _EMAIL_PATTERN.sub("***@***", text)
    return text


def redact_payload(payload: Any) -> Any:
    """**结构化**脱敏：逐字符串值脱敏，绝不改动 JSON 语法。

    为什么不能对 ``json.dumps`` 的结果直接跑 :func:`redact_sensitive`：
    正则会在**转义后的 JSON 文本**上工作，一旦匹配跨过 ``\\\\`` 边界，
    就可能把两个反斜杠吃掉一个，留下 ``\\U`` 这种非法转义——实测崩过一次：

        json.loads(redact_sensitive(json.dumps(case)))  →  Invalid \\escape
        （line 1 column 194463，报告写不出来，整轮 live 数据丢失）

    结构化脱敏从根上没有这个问题：字符串值单独脱敏，括号、引号、转义全由
    ``json.dumps`` 最后一次性负责。
    """

    if isinstance(payload, str):
        return redact_sensitive(payload)
    if isinstance(payload, dict):
        return {key: redact_payload(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [redact_payload(item) for item in payload]
    return payload
