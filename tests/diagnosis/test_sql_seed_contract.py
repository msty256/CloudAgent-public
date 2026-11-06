#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""sql 域 seed 契约的静态守门（P1 规格 §3-T1.4）——只读文件，不连库。

背景：``TestGtReverification`` 在配了 ``CLOUDAGENT_DB_DSN`` 的机器上逐题
真库复验 plan/index 断言；但在 CI 与无库机器上它整体 skip，seed 或
``verified_against`` 的漂移要等下一次有人配好 DSN 才会被发现。
本文件兜住"跳过"的下界，守三件事：

1. ``tests/fixtures/sql/seed.sql`` 的四条被断言依赖的显式事实：
   - ``CREATE INDEX`` 行不出现 orders 的 tenant_id / created_at /
     customer_id / status（sql-001/002/006/008/009 的 index_absent 前提）；
   - 含 ``idx_customers_region`` 的创建（index_present 前提）；
   - 含 ``ANALYZE``（行数估算 / n_distinct 断言依赖统计新鲜）；
   - 不含明文密码 / DSN。
2. 每道 ``static`` 的 sql 题，其 ``verified_against`` 必须引用 seed 文件路径
   ——static 的定义是"对着仓库内依据核过"，依据不在就名不副实。
3. 幂等契约：seed 里 ``TRUNCATE`` 的每张表，必须在本文件里有对应的
   ``CREATE TABLE IF NOT EXISTS``——``sync_seed_primary.sql`` 当年就是
   "假设别人会建表"而那个别人不存在，这条守门防同一个坑再踩一次。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.case_library import load_cases

#: 仓库根下的 seed 相对路径——static 案例的 verified_against 必须引用它
SEED_RELPATH = "tests/fixtures/sql/seed.sql"
SEED_PATH = Path(__file__).resolve().parents[2] / SEED_RELPATH

#: orders 上禁止出现索引的列（sql-001/002/006/008/009 的 index_absent 前提）
FORBIDDEN_INDEX_COLUMNS = ("tenant_id", "created_at", "customer_id", "status")

#: P1（2026-11-07）从 runtime 升级为 static 的 11 题——防止本文件空转：
#: 若这些题被降级回 runtime，这里会红，逼人显式承认口径变化
P1_STATIC_IDS = {
    "sql-001", "sql-002", "sql-003", "sql-004", "sql-005",
    "sql-006", "sql-007", "sql-008", "sql-009", "sql-013", "sql-014",
}

_CREATE_INDEX_LINE = re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\b", re.IGNORECASE)
_REGION_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+idx_customers_region\b",
    re.IGNORECASE,
)
_ANALYZE = re.compile(r"^\s*ANALYZE\s+\w+", re.MULTILINE | re.IGNORECASE)
_TRUNCATE = re.compile(r"^\s*TRUNCATE\s+(?:TABLE\s+)?([^;]+);", re.MULTILINE | re.IGNORECASE)
_CREATE_TABLE = re.compile(
    r"^\s*CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)", re.MULTILINE | re.IGNORECASE
)


def _seed_text() -> str:
    assert SEED_PATH.is_file(), (
        f"{SEED_RELPATH} 不存在——sql 域 11 题 static 的依据没了；"
        "若确要移除，必须先把相关案例降级回 runtime 并说明"
    )
    return SEED_PATH.read_text(encoding="utf-8")


class TestSeedExplicitFacts:
    """规格 §3-T1.4 第 1 条：seed 文件里的四条显式事实。"""

    def test_no_index_on_forbidden_order_columns(self) -> None:
        index_lines = [ln for ln in _seed_text().splitlines() if _CREATE_INDEX_LINE.match(ln)]
        # 自身健全性：正则必须真的扫到了索引行，否则下面的断言是空转
        assert index_lines, "seed.sql 里没有扫到任何 CREATE INDEX 行（守门失灵）"
        for line in index_lines:
            for column in FORBIDDEN_INDEX_COLUMNS:
                assert column not in line.lower(), (
                    f"CREATE INDEX 行出现了被 index_absent 断言禁止的列 {column!r}：{line!r}"
                )

    def test_customers_region_index_created(self) -> None:
        assert _REGION_INDEX.search(_seed_text()), (
            "seed.sql 必须创建 idx_customers_region（sql-003/004 的 index_present 前提）"
        )

    def test_analyze_present(self) -> None:
        assert _ANALYZE.search(_seed_text()), (
            "seed.sql 末尾必须 ANALYZE——行数估算 / n_distinct 断言依赖统计新鲜"
        )

    def test_no_credentials(self) -> None:
        text = _seed_text()
        assert "postgresql://" not in text, "seed.sql 不许内嵌 DSN"
        assert not re.search(r"password", text, re.IGNORECASE), "seed.sql 不许内嵌密码"


class TestStaticCasesCiteSeed:
    """规格 §3-T1.4 第 2 条：static 的 sql 题必须引用 seed 路径。"""

    @pytest.fixture(scope="class")
    def sql_cases(self) -> list[dict]:
        return load_cases("sql")

    def test_p1_upgrade_set_still_static(self, sql_cases: list[dict]) -> None:
        static_ids = {
            c["case_id"]
            for c in sql_cases if c["ground_truth"].get("verification") == "static"
        }
        missing = P1_STATIC_IDS - static_ids
        assert not missing, (
            f"P1 升级的 {len(P1_STATIC_IDS)} 题里出现了非 static：{sorted(missing)}——"
            "若是有意降级，需同步修改本文件与 test_case_meta.py 的锁死集合"
        )

    def test_verified_against_cites_seed_path(self, sql_cases: list[dict]) -> None:
        naked = [
            c["case_id"]
            for c in sql_cases
            if c["ground_truth"].get("verification") == "static"
            and SEED_RELPATH not in (c["ground_truth"].get("verified_against") or "")
        ]
        assert not naked, (
            "这些 static 题的 verified_against 没有引用 seed 文件路径：" + ", ".join(naked)
        )


class TestSeedIdempotencyContract:
    """规格 §3-T1.4 第 3 条：TRUNCATE 的表必须在本文件里建出来。"""

    def test_every_truncated_table_is_created_in_file(self) -> None:
        text = _seed_text()
        # 约定：seed 里的 TRUNCATE 写成单行多表形式（与现状一致）
        truncated = {
            name.strip().strip('"')
            for stmt in _TRUNCATE.findall(text)
            for name in stmt.split(",")
            if name.strip()
        }
        created = set(_CREATE_TABLE.findall(text))
        assert truncated, "seed.sql 里没有扫到任何 TRUNCATE 语句（守门失灵）"
        missing = truncated - created
        assert not missing, (
            f"TRUNCATE 的表 {sorted(missing)} 在 seed.sql 里没有对应的 "
            "CREATE TABLE IF NOT EXISTS——幂等重放会在空库上炸；"
            "要么在文件里建表，要么把灌数职责移交对应 seed 并写明"
        )
