#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""REPL session browser — terminal-based session picker for ``--resume`` (no ID).

Replaces the TUI-only ``ResumeConversation`` screen when the REPL is in use.
Lets the user browse, filter, search content, and pick a previous session.
"""

from __future__ import annotations
# pylint: disable=E0611,R1702,R1723

from datetime import datetime
from typing import Any, Sequence

from rich.console import Console
from rich.table import Table

from cloudagent_ext.repl.color_scheme import build_oklch_console
from cloudagent_ext.services.session_storage import SessionMetadata, SessionStorage


def browse_sessions_interactive(
    console: Console | None = None,
) -> str | None:
    """Show an interactive session browser in the terminal.

    Lists sessions from :class:`SessionStorage` and lets the user:
    - Enter a session ID (or prefix) to resume
    - Enter ``#<number>`` to pick by list index
    - Enter ``/search <text>`` to search within session content
    - Enter ``/show <num>`` to show full session ID for a row
    - Press Enter with empty input to cancel

    Returns the selected ``session_id`` or ``None`` if cancelled.
    """
    if console is None:
        console = build_oklch_console()

    metas = SessionStorage.list_sessions(limit=50)
    if not metas:
        console.print("[yellow]No past sessions found.[/yellow]")
        return None

    # Display session table
    _render_session_table(console, metas)
    _print_help(console)

    # Interactive selection
    while True:
        try:
            raw = input("\n❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return None

        if not raw:
            return None

        # Help
        if raw == "/help":
            _print_help(console)
            continue

        # Content search: /search <query>
        if raw.startswith("/search "):
            query = raw[8:].strip()
            if not query:
                console.print("[yellow]Usage: /search <text>[/yellow]")
                continue
            results = _search_session_content(metas, query)
            if not results:
                console.print(f"[yellow]No sessions contain '{query}'.[/yellow]")
            else:
                console.print(f"[green]Sessions matching '{query}':[/green]")
                _render_session_table(console, results)
                metas = list(results)  # Update working list for subsequent picks
            continue

        # Show full session ID (and the untruncated last input): /show <num>
        # Printed as plain lines, outside the table, so the text can be
        # selected and copied without the box-drawing characters.
        if raw.startswith("/show "):
            try:
                idx = int(raw[6:].strip()) - 1
                if 0 <= idx < len(metas):
                    _print_session_details(console, metas[idx])
                else:
                    console.print("[red]Index out of range.[/red]")
            except ValueError:
                console.print("[red]Usage: /show <number>[/red]")
            continue

        # Numeric selection: #<number>
        if raw.startswith("#"):
            try:
                idx = int(raw[1:])
                if 1 <= idx <= len(metas):
                    sid = metas[idx - 1].session_id
                    console.print(f"[green]Selected session: {sid[:8]}…[/green]")
                    return sid
            except ValueError:
                pass  # Invalid candidate; continue with the surrounding fallback.
            console.print("[red]Invalid selection. Use # followed by a number from the table.[/red]")
            continue

        # Prefix match against session ID
        matches = [m for m in metas if m.session_id.startswith(raw) or raw in m.session_id]
        if len(matches) == 1:
            sid = matches[0].session_id
            console.print(f"[green]Selected session: {sid[:8]}…[/green]")
            return sid
        elif len(matches) > 1:
            console.print("[yellow]Multiple matches — be more specific:[/yellow]")
            _render_session_table(console, matches)
            metas = list(matches)
            _print_help(console)
            continue
        else:
            # No ID match — try content search as fallback
            content_results = _search_session_content(metas, raw)
            if content_results:
                console.print(f"[green]No session ID match. Showing sessions whose content matches '{raw}':[/green]")
                _render_session_table(console, content_results)
                metas = list(content_results)
                _print_help(console)
            else:
                console.print(
                    "[red]No matches. Enter a session ID (or prefix), #<number>, "
                    "/search <text>, or press Enter to cancel.[/red]"
                )
            continue


def _extract_content_block_text(block: Any) -> str:
    """Extract searchable text from a ContentBlock (dataclass or dict).

    Handles all known ContentBlock types:
    ``TextBlock`` → .text
    ``ThinkingBlock`` → .thinking
    ``RedactedThinkingBlock`` → .data
    ``ToolUseBlock`` → .name + .input (stringified)
    ``ToolResultBlock`` → .content (recursively)
    dict fallback → "text" or "content" key
    """
    from cloudagent_ext.types.content_blocks import (
        RedactedThinkingBlock,
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
    )

    if isinstance(block, TextBlock):
        return block.text
    if isinstance(block, ThinkingBlock):
        return block.thinking
    if isinstance(block, RedactedThinkingBlock):
        return block.data
    if isinstance(block, ToolUseBlock):
        parts = [block.name]
        if isinstance(block.input, dict):
            parts.extend(str(v) for v in block.input.values())
        return " ".join(parts)
    if isinstance(block, ToolResultBlock):
        # content can be str or list[ContentBlock]
        if isinstance(block.content, str):
            return block.content
        if isinstance(block.content, list):
            return " ".join(_extract_content_block_text(cb) for cb in block.content)
        return str(block.content)
    if isinstance(block, dict):
        return str(block.get("text") or block.get("content") or "")
    # Fallback: any remaining dataclass or object
    return str(block)


def _search_session_content(
    metas: Sequence[SessionMetadata],
    query: str,
) -> list[SessionMetadata]:
    """Search session transcript content for ``query``.

    Returns the subset of *metas* whose transcript text contains *query*
    (case-insensitive). Falls back to searching metadata fields if loading
    the transcript fails.
    """
    query_lower = query.lower()
    results: list[SessionMetadata] = []
    for meta in metas:
        # First check metadata fields (fast path)
        if query_lower in (meta.last_user_input or "").lower():
            results.append(meta)
            continue
        if query_lower in (meta.title or "").lower():
            results.append(meta)
            continue

        # Slow path: load transcript text
        try:
            storage = SessionStorage(session_id=meta.session_id)
            messages = storage.read_messages()
            found = False
            for msg in messages:
                content = getattr(msg, "content", None) or ""
                if isinstance(content, str) and query_lower in content.lower():
                    found = True
                    break
                elif isinstance(content, list):
                    for item in content:
                        block_text = _extract_content_block_text(item)
                        if query_lower in block_text.lower():
                            found = True
                            break
                    if found:
                        break
            if found:
                results.append(meta)
        except Exception:  # nosec B110
            # Skip sessions that can't be loaded
            pass

    return results


def load_session_metadata_for_display(limit: int = 50) -> list[dict]:
    """Load session metadata for display.

    Returns a list of dicts with ``session_id``, ``time``, ``model``,
    ``message_count``, ``last_user_input``, ``title``.
    """
    metas = SessionStorage.list_sessions(limit=limit)
    out: list[dict] = []
    for meta in metas:
        ts = ""
        if meta.last_updated:
            try:
                ts = datetime.fromtimestamp(meta.last_updated).strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts = str(meta.last_updated)
        last_input = (meta.last_user_input or "")[:60]
        if len(last_input) == 60:
            last_input += "…"
        out.append(
            {
                "session_id": meta.session_id,
                "time": ts,
                "model": meta.model or "",
                "message_count": meta.message_count,
                "last_user_input": last_input,
                "title": meta.title or "",
            }
        )
    return out


# ---- internal helpers ----


# Column budget for :func:`_render_session_table`.
#
# 表格只保留挑会话真正需要的四列：# / Session ID / Time / Last input。
# Model 与 Msgs 不进表格（对挑选没有帮助，且挤占宽度），完整值都在
# ``/show <num>`` 里。
#
#   * Session ID —— 36 字符 uuid4，整条可见，否则没法复制出来给
#     ``cloudagent --resume <id>`` / ``/load <id>`` 用。
#   * Last input —— 单行、超出列宽省略即可（完整文本由 ``/show`` 提供），
#     这样一条会话永远只占一行，表格才好扫。
#
# ``_TABLE_CHROME_WIDTH`` = 每列分隔符 + 左右填充（3 字符）+ 收尾边框。
_FIXED_COLUMN_WIDTHS = 4 + 16  # # / Time
_TABLE_CHROME_WIDTH = 3 * 4 + 1
_FULL_ID_WIDTH = 36  # uuid4 形如 8-4-4-4-12
_ID_COLUMN_WIDTH = _FULL_ID_WIDTH + 2
_MIN_INPUT_WIDTH = 20


def _column_widths(console: Console) -> tuple[int, int]:
    """Return ``(session_id_width, last_input_width)`` for the current terminal.

    Falls back to a 100-column terminal when the console reports no width
    (e.g. piped output), so the table never collapses to a sliver.

    Only when the terminal is too narrow for a full 36-char ID *and* a usable
    Last input column does the ID degrade to an ellipsized form — even then
    ``/show <num>`` prints the complete ID.
    """
    usable = (console.width or 100) - _TABLE_CHROME_WIDTH - _FIXED_COLUMN_WIDTHS
    id_width = _ID_COLUMN_WIDTH
    input_width = usable - id_width
    if input_width < _MIN_INPUT_WIDTH:
        input_width = _MIN_INPUT_WIDTH
        id_width = max(usable - input_width, 12)
    return id_width, input_width


def _flatten(text: str) -> str:
    """Collapse whitespace/newlines so a row stays one logical line.

    Stored ``last_user_input`` keeps the user's original newlines, which made
    a single session span several table rows and left a half-sentence per
    line when copying.
    """
    return " ".join((text or "").split())


def _print_session_details(console: Console, meta: SessionMetadata) -> None:
    """Print the copy-friendly detail block used by ``/show <num>``.

    Plain ``key: value`` lines (no table, no box-drawing characters) so the
    full session ID and the untruncated last input can be selected and
    copied out of the terminal.
    """
    console.print(f"Session ID: {meta.session_id}")
    full_input = _flatten(meta.last_user_input)
    if full_input:
        console.print(f"Last input: {full_input}")
    if getattr(meta, "model", ""):
        console.print(f"Model: {meta.model}")
    if getattr(meta, "message_count", 0):
        console.print(f"Messages: {meta.message_count}")
    if getattr(meta, "title", ""):
        console.print(f"Title: {meta.title}")


def _render_session_table(console: Console, metas: Sequence[SessionMetadata]) -> None:
    """Render a table of sessions to the console."""
    id_width, input_width = _column_widths(console)
    table = Table(title="Past sessions", show_lines=False)
    table.add_column("#", style="dim", no_wrap=True, width=4)
    # 完整 UUID（36 字符）整列直出；只有终端窄到放不下时才由 Rich 省略，
    # 届时 ``/show <num>`` 仍能拿到全值。
    table.add_column(
        "Session ID",
        style="bold cyan",
        no_wrap=True,
        width=id_width,
        overflow="ellipsis",
    )
    table.add_column("Time", style="green", no_wrap=True, width=16)
    # Last input 只作概览：单行 + 超长省略，完整文本交给 ``/show <num>``。
    table.add_column(
        "Last input",
        style="white",
        width=input_width,
        no_wrap=True,
        overflow="ellipsis",
    )

    for idx, meta in enumerate(metas, start=1):
        ts = ""
        if meta.last_updated:
            try:
                ts = datetime.fromtimestamp(meta.last_updated).strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts = str(meta.last_updated)

        last_input = _flatten(meta.last_user_input)

        table.add_row(
            str(idx),
            meta.session_id,
            ts,
            last_input or "(no input)",
        )

    console.print(table)


def _print_help(console: Console) -> None:
    """Print help hints."""
    console.print(
        "[dim]Enter a session ID (or prefix) to resume · "
        "#<num> to pick by number · "
        "/search <text> to search content · "
        "/show <num> for full ID, input, model and messages · "
        "Enter to cancel[/dim]"
    )


__all__ = [
    "browse_sessions_interactive",
    "load_session_metadata_for_display",
]
