"""Workspace search backends (components C5).
UI-neutral helpers behind the TUI's global-search and quick-open dialogs
,
both ripgrep-backed via the shared ``tool_system.utils.ripgrep`` runner.
Insertion formats are -verbatim:
* content match → ``@{file}#L{line} `` 
* file → ``@{path} `` 
Divergences (documented): no live preview pane and no open-in-editor
action (no editor-spawn analog exists — same decision as `/memory`);
dialogs are reached via ``/search`` and ``/open`` instead of the 
ctrl+shift chords (terminals commonly swallow them; revisit with the
keybindings phase).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

#: MAX_MATCHES_PER_FILE=10 (rg -m),
# MAX_TOTAL_MATCHES=500 parsed total.
_PER_FILE_MATCH_CAP = 10
_MAX_RESULTS = 500

#: "a simple split on the first colon
# would mangle the path [Windows drive letters] — use a regex".
_LINE_RE = re.compile(r"^(.*?):(\d+):(.*)$")


def _to_posix_rel(path: str, cwd: str) -> str:
    rel = os.path.relpath(path, cwd) if os.path.isabs(path) else path
    # quick-open normalizes to forward slashes for the mention text.
    return rel.replace(os.sep, "/") if os.sep != "/" else rel


@dataclass(frozen=True)
class ContentMatch:
    file: str  # relative to the search root
    line: int
    text: str

    def insertion(self) -> str:
        return f"@{self.file}#L{self.line} "

    def label(self) -> str:
        return f"{self.file}:{self.line}"


def file_insertion(path: str) -> str:
    return f"@{path} "


def search_content(
    query: str,
    cwd: str,
    *,
    max_results: int = _MAX_RESULTS,
    abort_signal: Any | None = None,
) -> tuple[list[ContentMatch], bool]:
    """Fixed-string, case-insensitive content search ( rg args:
     ``-i -F``). Returns ``(matches,
    truncated)`` — truncated=True when the parse hit ``max_results``."""

    query = (query or "").strip()
    if not query:
        return [], False
    from cloudagent_ext.tool_system.utils.ripgrep import ripgrep

    lines = ripgrep(
        [
            "-n",
            "--no-heading",
            "-i",
            "--fixed-strings",
            "-m",
            str(_PER_FILE_MATCH_CAP),
            "--",
            query,
        ],
        cwd,
        abort_signal=abort_signal,
    )
    matches: list[ContentMatch] = []
    truncated = False
    for raw in lines:
        if len(matches) >= max_results:
            truncated = True
            break
        parsed = _LINE_RE.match(raw)
        if not parsed:
            continue
        file_part, line_part, text = parsed.groups()
        matches.append(
            ContentMatch(
                file=_to_posix_rel(file_part, cwd),
                line=int(line_part),
                text=text.strip()[:200],
            )
        )
    return matches, truncated


def list_workspace_files(
    cwd: str, *, max_files: int = 5000, abort_signal: Any | None = None
) -> tuple[list[str], bool]:
    """All tracked-ish files (``rg --files`` honors.gitignore), POSIX-
    relative. Returns ``(files, truncated)``."""

    from cloudagent_ext.tool_system.utils.ripgrep import ripgrep

    lines = ripgrep(["--files"], cwd, abort_signal=abort_signal)
    truncated = len(lines) > max_files
    return [_to_posix_rel(raw, cwd) for raw in lines[:max_files]], truncated


def filter_files(files: list[str], query: str, *, limit: int = 50) -> list[str]:
    """Fuzzy-ranked filter (same scorer as the history search)."""

    query = (query or "").strip()
    if not query:
        return files[:limit]
    from cloudagent_ext.services.fuzzy_match import fuzzy_score

    scored: list[tuple[int, str]] = []
    for path in files:
        matched, score = fuzzy_score(path, query)
        if matched:
            scored.append((score, path))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [path for _score, path in scored[:limit]]


__all__ = [
    "ContentMatch",
    "file_insertion",
    "filter_files",
    "list_workspace_files",
    "search_content",
]
