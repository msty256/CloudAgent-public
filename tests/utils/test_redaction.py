#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""脱敏规则的直接单测（EVAL-P0）。

背景：``redact_sensitive`` / ``redact_payload`` 原先只在评测链路里被间接用到，
搬到 ``cloudagent_ext/utils/redaction.py`` 后补上直接契约——
日志工具（产品）与评测报告（评测）共用这套规则，规则漂移在这里拦住。
"""

from __future__ import annotations

import json

from cloudagent_ext.utils.redaction import redact_payload, redact_sensitive


class TestRedactSensitive:
    def test_dsn_password_masked(self) -> None:
        assert (
            redact_sensitive("postgresql://user:pass@host:5433/db")
            == "postgresql://user:***@host:5433/db"
        )

    def test_already_redacted_dsn_unchanged(self) -> None:
        """幂等：已脱敏形态不许被二次改写。"""

        text = "postgresql://user:***@host/db"
        assert redact_sensitive(text) == text

    def test_password_assignment_masked(self) -> None:
        assert redact_sensitive("password=secret123") == "password=***"

    def test_api_key_masked(self) -> None:
        assert redact_sensitive("sk-abcdef123456") == "***"

    def test_phone_masked(self) -> None:
        assert redact_sensitive("13800138000") == "1**********"

    def test_email_masked(self) -> None:
        assert redact_sensitive("alice@example.com") == "***@***"

    def test_empty_string_unchanged(self) -> None:
        assert redact_sensitive("") == ""


class TestRedactPayload:
    def test_json_syntax_preserved(self) -> None:
        """结构化脱敏不许破坏 JSON 语法（report.py docstring 里实测崩过的场景）。"""

        payload = {"a": "postgresql://u:p@h/d", "nested": {"b": ["x", "13800138000"]}}
        out = redact_payload(payload)
        # 逐值脱敏后仍可完整序列化/解析
        assert json.loads(json.dumps(out)) == out
        assert out["a"] == "postgresql://u:***@h/d"
        assert out["nested"]["b"][1] == "1**********"

    def test_non_string_scalars_pass_through(self) -> None:
        payload = {"n": 42, "f": 1.5, "b": True, "none": None}
        assert redact_payload(payload) == payload
