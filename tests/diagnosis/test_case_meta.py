#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""case 集校验元数据的守护测试（2026-11-01 体检后新增）。

背景：2026-11-01 体检时 38 题里只有 15 题能在仓库内核实，但正确率一直在用
全 38 题算；`code-007` 的 gt 过期（描述已修掉的旧行为）就是被这个盲区藏住的。
2026-11-07 P1 把 sql 域 seed 迁入仓库后，sql 域 11 题升级为 `static`，
仓库内可复核的分母从 17 提到 28。

这里守三件事：

1. **每道题都得说清"怎么核的"**——新题不标 `verification` 直接红；
2. **`static` 必须给出核对依据**（`verified_against`），不许空口说"核过了"；
3. **分布数字被锁死**——把题从 `static` 偷偷降级成 `external` 会让测试红，
   逼人显式承认"这题现在核不了了"，而不是让指标悄悄变好看。

第 3 条看起来"太硬"，但它防的正是这次的真实教训：**没人会主动把坏消息写进报告**。
"""

from __future__ import annotations

import pytest

from cloudagent_ext.diagnosis.case_audit import audit_cases, format_audit
from cloudagent_ext.diagnosis.case_library import (
    VALID_VERIFICATIONS,
    load_cases,
    validate_case,
)

#: 2026-11-01 体检定版：任何变动都必须是有意识的。
#: 2026-11-07 P1：sql 域 seed 迁入仓库（tests/fixtures/sql/seed.sql），
#: 11 题 runtime → static（sql-001..009/013/014），分布 17/15/6 → 28/4/6。
#: runtime 余 4 = sql-010/011/012 + sync-001（能力边界/环境降级/协议行为，非数据问题）。
EXPECTED_TOTAL = 38
EXPECTED_STATIC = 28
EXPECTED_RUNTIME = 4
EXPECTED_EXTERNAL = 6


@pytest.fixture(scope="module")
def all_cases() -> list[dict]:
    rows: list[dict] = []
    for domain in ("code", "sql", "log", "cross", "sync"):
        rows.extend(load_cases(domain))
    return rows


def _gt(case: dict) -> dict:
    return case["ground_truth"]


class TestEveryCaseHasVerification:
    def test_no_missing_field(self, all_cases: list[dict]) -> None:
        missing = [c["case_id"] for c in all_cases if not _gt(c).get("verification")]
        assert not missing, (
            "这些题没有 ground_truth.verification —— 新题必须标注怎么核的："
            + ", ".join(missing)
        )

    def test_value_in_domain(self, all_cases: list[dict]) -> None:
        for case in all_cases:
            value = _gt(case).get("verification")
            assert value in VALID_VERIFICATIONS, f"{case['case_id']} verification={value!r}"

    def test_static_requires_evidence(self, all_cases: list[dict]) -> None:
        """``static`` 是"对着代码核过"，那就必须说清对着哪儿。"""

        naked = [
            c["case_id"]
            for c in all_cases
            if _gt(c).get("verification") == "static" and not _gt(c).get("verified_against")
        ]
        assert not naked, "static 但没写 verified_against：" + ", ".join(naked)

    def test_all_cases_still_validate(self, all_cases: list[dict]) -> None:
        """加了新字段之后，原有 schema 校验不能被撑破。"""

        for case in all_cases:
            validate_case(case)


class TestDistributionLocked:
    def test_total(self, all_cases: list[dict]) -> None:
        assert len(all_cases) == EXPECTED_TOTAL

    def test_counts(self, all_cases: list[dict]) -> None:
        summary = audit_cases(
            [
                {
                    "case_id": c["case_id"],
                    "domain": c["domain"],
                    "verification": _gt(c)["verification"],
                }
                for c in all_cases
            ]
        )
        assert summary["statically_verifiable"] == EXPECTED_STATIC
        assert summary["needs_runtime_env"] == EXPECTED_RUNTIME
        assert summary["unverifiable"] == EXPECTED_EXTERNAL

    def test_static_set_is_exact(self, all_cases: list[dict]) -> None:
        """锁住具体是哪 28 题——降级/新增都必须显式改这张表。"""

        expected = {
            "code-001", "code-002", "code-003", "code-004", "code-005", "code-006", "code-007",
            "log-001", "log-002", "log-003", "log-004", "log-005", "log-006",
            "sql-001", "sql-002", "sql-003", "sql-004", "sql-005",
            "sql-006", "sql-007", "sql-008", "sql-009", "sql-013", "sql-014",
            "sync-002", "sync-003", "sync-004", "sync-005",
        }
        actual = {c["case_id"] for c in all_cases if _gt(c).get("verification") == "static"}
        assert actual == expected


class TestAuditRatiOnlyCountsStatic:
    def test_measurable_now_excludes_runtime(self, all_cases: list[dict]) -> None:
        """口径红线：``runtime`` 不是"现在能核"，只是"有环境才能核"。"""

        summary = audit_cases(
            [
                {
                    "case_id": c["case_id"],
                    "domain": c["domain"],
                    "verification": _gt(c)["verification"],
                }
                for c in all_cases
            ]
        )
        assert summary["measurable_now"] == EXPECTED_STATIC
        assert summary["measurable_with_env"] == EXPECTED_STATIC + EXPECTED_RUNTIME
        # 两者绝不能相等，否则说明口径又混了
        assert summary["measurable_now"] != summary["measurable_with_env"]

    def test_format_mentions_both_buckets(self, all_cases: list[dict]) -> None:
        summary = audit_cases(
            [
                {
                    "case_id": c["case_id"],
                    "domain": c["domain"],
                    "verification": _gt(c)["verification"],
                }
                for c in all_cases
            ]
        )
        text = format_audit(summary)
        assert "现在就能复核" in text
        assert "需运行期环境" in text
        assert "无法复核" in text


class TestFixedGroundTruth:
    """三题过期款的修复不能被悄悄回退。"""

    def test_code_001_says_wired(self) -> None:
        case = next(c for c in load_cases("code") if c["case_id"] == "code-001")
        desc = _gt(case)["root_causes"][0]["description"]
        assert "runtime_session" in desc
        assert "零接线" in str(_gt(case)["forbidden_findings"])

    def test_code_006_says_three_domains(self) -> None:
        case = next(c for c in load_cases("code") if c["case_id"] == "code-006")
        desc = _gt(case)["root_causes"][0]["description"]
        assert "_AUGMENTERS" in desc
        assert "不再做 agent_type 早退" in desc

    def test_code_007_points_at_run_assessor(self) -> None:
        case = next(c for c in load_cases("code") if c["case_id"] == "code-007")
        gt = _gt(case)
        assert "_run_assessor" in gt["root_causes"][0]["description"]
        # 旧 gt 把"异步已覆盖校验"列为禁止发现，现在是事实，必须改掉
        assert "异步已覆盖校验" not in gt["forbidden_findings"]
