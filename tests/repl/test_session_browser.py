#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""/resume session browser 的显示契约测试（离线）。

表格只保留四列：# / Session ID / Time / Last input。
- Session ID 必须整条可见（36 字符 uuid4），否则没法复制给 ``--resume`` 用；
- Last input 是**概览**：单行、超长省略，完整文本由 ``/show <num>`` 提供；
- Model / Msgs 不进表格，同样在 ``/show <num>`` 里拿。

修复前的四个问题都在下面被反向锁定：
1. ``last_user_input`` 被硬截到 57 字符 + "…"（数据层丢信息）；
2. 列宽写死、不随终端自适应，ID 只剩 8 位前缀；
3. 原始换行把一条会话拆成多行；
4. 没有任何"拿到完整文本"的出口。
"""

from __future__ import annotations

import re
import time
from io import StringIO

from rich.console import Console

from cloudagent_ext.repl import session_browser as sb
from cloudagent_ext.services.session_storage import SessionMetadata

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_LONG_INPUT = (
    "那 tenants 下游那 8 行是哪来的？帮我查一下写入来源，顺便确认是不是环境："
    "上游 primary、下游 secondary 的数据同步把空数据带进来了"
)


def _console(width: int = 120) -> tuple[Console, StringIO]:
    buf = StringIO()
    return (
        Console(file=buf, width=width, force_terminal=True, no_color=True),
        buf,
    )


def _meta(**kwargs) -> SessionMetadata:
    base = {
        # 真实 session id 是 36 字符 uuid4（8-4-4-4-12）
        "session_id": "e54e9104-1b2c-4d3e-8f90-a1b2c3d4e5f6",
        "model": "deepseek-ai/DeepSeek-V4-Pro",
        "message_count": 57,
        "last_updated": time.time(),
    }
    base.update(kwargs)
    return SessionMetadata(**base)


def _plain(buf: StringIO) -> str:
    """去掉 ANSI 转义后的渲染文本。"""
    return _ANSI_RE.sub("", buf.getvalue())


def test_flatten_collapses_newlines_and_runs_of_space() -> None:
    assert sb._flatten("第一行\n第二行") == "第一行 第二行"
    assert sb._flatten("a  \n\n  b") == "a b"
    assert sb._flatten("") == ""
    assert sb._flatten(None) == ""  # type: ignore[arg-type]


def test_table_shows_the_full_session_id() -> None:
    """Session ID 必须整条可见，不能用 8 位前缀 + … 代替。"""

    console, buf = _console(width=120)
    meta = _meta(last_user_input=_LONG_INPUT)
    sb._render_session_table(console, [meta])

    rendered = _plain(buf)
    assert meta.session_id in rendered
    assert meta.session_id[:8] + "…" not in rendered


def test_table_keeps_last_input_on_one_line_and_ellipsizes() -> None:
    """Last input 是概览：一条会话只占一行，超长用 … 收尾（完整值走 /show）。"""

    console, buf = _console(width=120)
    sb._render_session_table(console, [_meta(last_user_input=_LONG_INPUT)])

    rendered = _plain(buf)
    matching = [line for line in rendered.splitlines() if "那 tenants" in line]
    assert len(matching) == 1, "超长输入不应折成多行"
    assert "…" in rendered


def test_table_shows_short_input_in_full() -> None:
    """放得下的输入照原样显示，多余的换行被压成空格。"""

    console, buf = _console(width=120)
    sb._render_session_table(console, [_meta(last_user_input="第一行\n第二行")])

    rendered = _plain(buf)
    assert "第一行 第二行" in rendered
    assert "…" not in rendered


def test_show_details_prints_full_id_input_model_and_messages() -> None:
    """/show <num> 是完整信息的出口：可整段复制，无表格边框。"""

    meta = _meta(last_user_input="第一行\n第二行", title="订单诊断")
    console, buf = _console(width=120)
    sb._print_session_details(console, meta)

    rendered = _plain(buf)
    assert meta.session_id in rendered  # 完整 ID
    assert "第一行 第二行" in rendered  # 完整输入
    assert "deepseek-ai/DeepSeek-V4-Pro" in rendered  # 表格里不再显示的 model
    assert "Messages: 57" in rendered  # 表格里不再显示的 Msgs
    assert "订单诊断" in rendered
    assert "│" not in rendered


def test_column_widths_reserve_the_full_id_when_possible() -> None:
    console, _ = _console(width=120)
    id_width, input_width = sb._column_widths(console)
    assert id_width == sb._ID_COLUMN_WIDTH  # 放得下 → 不缩
    assert input_width >= sb._MIN_INPUT_WIDTH


def test_column_widths_shrink_id_only_on_a_narrow_terminal() -> None:
    """窄到装不下完整 ID 时，先保住 Last input，ID 才退化（/show 仍给全值）。"""

    narrow, _ = _console(width=60)
    id_width, input_width = sb._column_widths(narrow)
    assert input_width >= sb._MIN_INPUT_WIDTH
    assert id_width < sb._ID_COLUMN_WIDTH
