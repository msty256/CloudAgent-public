#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""中立文本匹配工具（变更 add-gap-driven-orchestration）。

为什么单独一个模块：

* 缺口判定（生产编排）与评分器（`evaluation/scoring.py`）都需要
  "关键词全部出现 + 术语归一"这一能力；
* 但 `evaluation/scoring.py` 头部 `import` 了 `evaluation.safety`——若让生产代码
  直接依赖它，将来裁掉/替换 evaluation 会连带断掉编排（反向分层）；
* 因此把三个符号放在这里，两边**都从这里 import**，保持"一份实现"。

**增补纪律**：`TERM_EQUIVALENTS` 同时影响**评分口径**与**生产缺口判定**。
只允许收录"同一概念"的表述变体（如「全表扫描」≈「seq scan」），
每次增补须经留痕回放评审——改这里等于改生产行为。

另提供缺口命题的**结构化关键词抽取**（不依赖中文分词：仓库无分词依赖、
无停用词表；中文叙述部分不参与匹配，属于有意接受的保守代价）。
"""

from __future__ import annotations

import re

__all__ = [
    "ASCII_STOPWORDS",
    "TERM_EQUIVALENTS",
    "normalize_text",
    "contains_all",
    "normalize_statement",
    "extract_keywords",
]

# ---------------------------------------------------------------------------
# 术语归一（原 evaluation/scoring.py，搬家而来）
# ---------------------------------------------------------------------------

TERM_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "全表扫描": (
        "全表顺序扫描",
        "整表顺序扫描",
        "整表扫描",
        "seq scan",
        "sequential scan",
        "顺序扫描",
    ),
}


def normalize_text(text: str) -> str:
    """把同一概念的表述变体替换为规范词（大小写不敏感；长变体优先）。"""

    result = text.casefold()
    for canonical, variants in TERM_EQUIVALENTS.items():
        for variant in sorted(variants, key=len, reverse=True):
            result = result.replace(variant.casefold(), canonical.casefold())
    return result


def contains_all(haystack: str, terms: list[str], *, normalize: bool = False) -> bool:
    """``terms`` 中的每个词都出现在 ``haystack`` 里（空词表返回 False）。"""

    usable = [t for t in terms if isinstance(t, str) and t.strip()]
    if not usable:
        return False
    if normalize:
        folded = normalize_text(haystack)
        return all(normalize_text(t) in folded for t in usable)
    folded = haystack.casefold()
    return all(t.casefold() in folded for t in usable)


# ---------------------------------------------------------------------------
# 缺口命题：归一化与关键词抽取
# ---------------------------------------------------------------------------

# 唯一停用词清单（design/tasks/spec 只引用这个常量，不再各自写数字）
ASCII_STOPWORDS = frozenset(
    {"the", "and", "or", "is", "are", "not", "to", "of", "in", "for", "with", "a", "an"}
)

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
_QUOTED_RE = re.compile(r"`([^`]{2,})`|\"([^\"]{2,})\"")
_NUMBER_RE = re.compile(r"\b\d{2,}\b")
_TRAILING_PUNCT = "。．.？?！!；;：:，,、 "


def normalize_statement(text: str) -> str:
    """命题归一化：压空白、转小写、去尾标点（用于去重）。"""

    folded = " ".join(str(text or "").split()).casefold()
    return folded.rstrip(_TRAILING_PUNCT)


def extract_keywords(text: str) -> list[str]:
    """从命题里抽结构化关键词（抽不出则返回空列表）。

    规则（design D3）：ASCII 标识符、引号/反引号包裹的 token、长度 ≥2 的数字。
    **不做中文分词**——中文叙述部分不参与匹配，属于有意接受的保守代价。
    """

    raw = str(text or "")
    found: list[str] = []
    for match in _QUOTED_RE.finditer(raw):
        found.append(match.group(1) or match.group(2) or "")
    for match in _IDENTIFIER_RE.finditer(raw):
        token = match.group(0)
        if token.casefold() in ASCII_STOPWORDS:
            continue
        found.append(token)
    found.extend(_NUMBER_RE.findall(raw))

    seen: set[str] = set()
    keywords: list[str] = []
    for item in found:
        lowered = item.strip().casefold()
        if not lowered or len(lowered) < 2 or lowered in seen:
            continue
        seen.add(lowered)
        keywords.append(lowered)
    return keywords
