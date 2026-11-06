#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""结构归约器测试（阶段 3 · T3.1）。

归约器的验收标准不是"变短了"，而是 **变短之后关键信息没丢**。
所以这里每条"该折"的用例都配一条"不许丢"的断言，重点盯三类容易丢的东西：

1. **离群行**——纯聚合（min/max/mean）会把"只有一行不对劲"吃干抹净，
   而那一行常常就是线索；
2. **头尾**——首行往往带"第一条/最早一条"，尾行带"最新一条"；
3. **空值**——空值常常就是根因（"这个字段一直是 NULL"），不能被均值抹掉。

另一半用例测**不该折就不折**：拿不准一律返回 ``None``，让调用方保留原文。
"折丢了"比"没折"严重得多。
"""

from __future__ import annotations

import pytest

from cloudagent_ext.context_system.reducers import (
    Reduced,
    reduce_log_block,
    reduce_sql_rows,
    render_summary,
)


def _rows(count: int, *, outlier: bool = False) -> list[dict]:
    rows = []
    for index in range(1, count + 1):
        amount = 999_999.0 if (outlier and index == count // 2) else float(index * 10)
        rows.append(
            {
                "id": index,
                "order_no": f"order-{index}",
                "tenant_id": f"tenant-{index % 8:03d}",
                "amount": amount,
                "status": "paid" if index % 2 else "pending",
            }
        )
    return rows


def _payload(rows: list[dict], **extra) -> dict:
    payload = {
        "mode": "rows",
        "table": "public.orders",
        "target": "primary",
        "returned": len(rows),
        "truncated": False,
        "rows": rows,
    }
    payload.update(extra)
    return payload


class TestSqlShouldNotReduce:
    def test_too_few_rows(self) -> None:
        """行数少时摘要比原文还长，折了纯亏。"""

        assert reduce_sql_rows(_payload(_rows(5))) is None

    def test_aggregate_mode(self) -> None:
        assert reduce_sql_rows({"mode": "aggregate", "count": 50000}) is None

    def test_not_a_dict(self) -> None:
        assert reduce_sql_rows(None) is None
        assert reduce_sql_rows("rows") is None

    def test_empty_rows(self) -> None:
        assert reduce_sql_rows(_payload([])) is None


class TestSqlKeepsWhatMatters:
    def test_head_and_tail_preserved(self) -> None:
        rows = _rows(200)
        reduced = reduce_sql_rows(_payload(rows), max_rows=5)
        assert reduced is not None
        assert reduced.payload["head"] == rows[:5]
        assert reduced.payload["tail"] == rows[-5:]

    def test_outlier_row_is_not_swallowed(self) -> None:
        """核心用例：一个离群值必须能从摘要里看出来。

        纯 min/max/mean 会把它压成一个数字；这里要求它作为"极值行"被单独拎出来。
        """

        rows = _rows(200, outlier=True)
        reduced = reduce_sql_rows(_payload(rows), max_rows=3)
        assert reduced is not None

        extremes = reduced.payload["extremes"]
        outlier_rows = [item for item in extremes if item["value"] == 999_999.0]
        assert outlier_rows, f"离群值没被提取：{extremes}"
        assert outlier_rows[0]["column"] == "amount"
        # 而且还能定位到具体行
        assert outlier_rows[0]["row"]["amount"] == 999_999.0

    def test_numeric_stats(self) -> None:
        reduced = reduce_sql_rows(_payload(_rows(200)))
        assert reduced is not None
        stats = reduced.payload["numeric"]["amount"]
        assert stats["min"] == 10.0
        assert stats["max"] == 2000.0
        assert stats["mean"] == pytest.approx(1005.0)

    def test_low_cardinality_distribution(self) -> None:
        reduced = reduce_sql_rows(_payload(_rows(200)))
        assert reduced is not None
        assert reduced.payload["categorical"]["status"] == {"paid": 100, "pending": 100}

    def test_high_cardinality_column_not_distributed(self) -> None:
        """order_no 有 200 个不同值，做分布会把摘要撑爆——必须跳过。"""

        reduced = reduce_sql_rows(_payload(_rows(200)))
        assert reduced is not None
        assert "order_no" not in reduced.payload["categorical"]

    def test_null_count_recorded(self) -> None:
        rows = _rows(50)
        for row in rows[:7]:
            row["order_no"] = None
        reduced = reduce_sql_rows(_payload(rows))
        assert reduced is not None
        assert reduced.payload["nulls"]["order_no"] == 7

    def test_bool_is_not_a_number(self) -> None:
        """``True`` 是 ``int`` 的子类，不能混进数值统计。"""

        rows = [{"id": i, "flag": bool(i % 2)} for i in range(1, 60)]
        reduced = reduce_sql_rows(_payload(rows))
        assert reduced is not None
        assert "flag" not in reduced.payload["numeric"]

    def test_redacted_columns_carried_over(self) -> None:
        reduced = reduce_sql_rows(_payload(_rows(100), redacted_columns=["phone"]))
        assert reduced is not None
        assert reduced.payload["redacted_columns"] == ["phone"]

    def test_summary_shorter_than_original(self) -> None:
        rows = _rows(200)
        reduced = reduce_sql_rows(_payload(rows))
        assert reduced is not None
        assert reduced.reduced_chars < reduced.original_chars

    def test_render_mentions_key_facts(self) -> None:
        reduced = reduce_sql_rows(_payload(_rows(200, outlier=True)))
        assert reduced is not None
        text = render_summary(reduced)
        assert "200 行" in text
        assert "public.orders" in text
        assert "status" in text
        assert "极值行" in text


class TestLogShouldNotReduce:
    def test_too_few_lines(self) -> None:
        text = "\n".join(
            f"2026-10-22 09:00:0{i}.100 ERROR [w] C - NullPointerException" for i in range(5)
        )
        assert reduce_log_block(text) is None

    def test_no_timestamp_means_not_a_log(self) -> None:
        text = "\n".join(f"这是第 {i} 行普通文字，没有任何时间戳" for i in range(60))
        assert reduce_log_block(text) is None

    def test_no_error_lines(self) -> None:
        text = "\n".join(
            f"2026-10-22 09:00:{i % 60:02d}.100 INFO [w] C - started" for i in range(60)
        )
        assert reduce_log_block(text) is None

    def test_not_a_string(self) -> None:
        assert reduce_log_block(None) is None
        assert reduce_log_block({"a": 1}) is None


class TestLogKeepsWhatMatters:
    def _log(self, count: int = 60) -> str:
        lines = []
        for index in range(count):
            if index % 3 == 0:
                lines.append(
                    f"2026-10-22 09:00:{index % 60:02d}.100 ERROR [w] com.example.svcb.R - "
                    f"java.lang.NullPointerException: tenant config missing [a1b2]"
                )
            else:
                lines.append(
                    f"2026-10-22 09:00:{index % 60:02d}.200 INFO [w] com.example.svca.C - ok [{index}]"
                )
        return "\n".join(lines)

    def test_time_range(self) -> None:
        reduced = reduce_log_block(self._log())
        assert reduced is not None
        span = reduced.payload["time_range"]
        assert span["first"].startswith("2026-10-22 09:00")
        assert span["last"].startswith("2026-10-22 09:00")

    def test_fingerprint_clustered_by_exception(self) -> None:
        text = self._log(60)
        reduced = reduce_log_block(text)
        assert reduced is not None
        prints = reduced.payload["fingerprints"]
        npe = [item for item in prints if "NullPointerException" in item["fingerprint"]]
        assert npe, prints
        assert npe[0]["count"] == 20  # 60 行里 index%3==0 的有 20 条

    def test_severity_counts(self) -> None:
        reduced = reduce_log_block(self._log(60))
        assert reduced is not None
        assert reduced.payload["severity"]["ERROR"] == 20

    def test_summary_shorter_than_original(self) -> None:
        text = self._log(120)
        reduced = reduce_log_block(text)
        assert reduced is not None
        assert reduced.reduced_chars < reduced.original_chars

    def test_render_mentions_fingerprint(self) -> None:
        reduced = reduce_log_block(self._log(60))
        assert reduced is not None
        text = render_summary(reduced)
        assert "NullPointerException" in text
        assert "时间范围" in text


class TestRenderSafety:
    def test_none_safe(self) -> None:
        assert render_summary(None) == ""  # type: ignore[arg-type]

    def test_unknown_kind(self) -> None:
        assert render_summary(Reduced(kind="mystery", payload={})) == ""

    def test_as_dict_roundtrip(self) -> None:
        reduced = reduce_sql_rows(_payload(_rows(100)))
        assert reduced is not None
        payload = reduced.as_dict()
        assert payload["kind"] == "sql_rows"
        assert payload["payload"]["row_count"] == 100


class TestNoExceptions:
    """归约器在脏数据上不能抛异常。

    注意这里**不要求一律返回 None**：形状错（rows 不是 list、行不是 dict）才该放弃；
    只是内容奇怪（同一列全是常数、值不可序列化）时照样能折——折完更短就行。
    """

    @pytest.mark.parametrize(
        "payload",
        [
            {"mode": "rows", "rows": "not-a-list"},
            {"mode": "rows", "rows": [None] * 30},
            {"mode": "rows", "rows": ["a", "b"] * 20},
            {},
            {"mode": "rows"},
        ],
    )
    def test_bad_shape_returns_none(self, payload) -> None:
        assert reduce_sql_rows(payload) is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"mode": "rows", "rows": [{"a": object()}] * 30},
            {"mode": "rows", "rows": [{"a": 1}] * 30},
            {"mode": "rows", "rows": [{"a": None, "b": 2}] * 25},
        ],
    )
    def test_weird_content_still_safe(self, payload) -> None:
        """内容奇怪但形状合法：允许归约，只要求不抛、且不崩成空。"""

        reduced = reduce_sql_rows(payload)
        if reduced is not None:
            assert reduced.payload["row_count"] == 30 or reduced.payload["row_count"] == 25
            assert isinstance(render_summary(reduced), str)

    @pytest.mark.parametrize("text", ["", "   ", "\n" * 100, "2026-01-01 00:00:00.000"])
    def test_log_dirty_input(self, text: str) -> None:
        assert reduce_log_block(text) is None
