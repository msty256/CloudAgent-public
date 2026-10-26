#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``connection`` 层离线单测（不依赖数据库）。

覆盖：DSN 仅从环境变量读取、缺失时给出配置指引、脱敏（URI 与 key=value 两种形式）。
"""

from __future__ import annotations

import pytest

pytest.importorskip("psycopg")

from cloudagent_ext.diagnosis.db.connection import (  # noqa: E402
    DSN_ENV_VAR,
    DbConnectionError,
    load_dsn,
    redact_dsn,
)


def test_load_dsn_from_mapping() -> None:
    dsn = "postgresql://u:p@h:5433/db"
    assert load_dsn({DSN_ENV_VAR: dsn}) == dsn


def test_load_dsn_missing_gives_configuration_guidance() -> None:
    with pytest.raises(DbConnectionError) as excinfo:
        load_dsn({})
    text = str(excinfo.value)
    assert DSN_ENV_VAR in text
    assert "config.json" in text


def test_load_dsn_ignores_blank() -> None:
    with pytest.raises(DbConnectionError):
        load_dsn({DSN_ENV_VAR: "   "})


def test_redact_dsn_uri_form() -> None:
    out = redact_dsn("postgresql://cloudagent_ro:s3cret@127.0.0.1:5433/cloudagent_sim")
    assert "s3cret" not in out
    assert out == "postgresql://cloudagent_ro:***@127.0.0.1:5433/cloudagent_sim"


def test_redact_dsn_key_value_form() -> None:
    out = redact_dsn("host=127.0.0.1 password=s3cret dbname=x")
    assert "s3cret" not in out
    assert "***" in out


def test_redact_dsn_without_password_unchanged() -> None:
    dsn = "postgresql://cloudagent_ro@127.0.0.1:5433/cloudagent_sim"
    assert redact_dsn(dsn) == dsn
