# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""from_config — Declarative YAML-snippet context provider.

Registers a ``register_section`` builder that reads user-declared context
snippets from ``.cloudagent/context_sections.yaml`` (relative to ``cwd``)
and injects them as a single "Declared Config" block at ``order=57``.

The YAML file has the following format:

.. code-block:: yaml

    # .cloudagent/context_sections.yaml
    sections:
      - title: "Project Context"
        content: "This project is a …"
      - title: "Current Sprint"
        content: "We're working on …"

Usage
-----
Importing this module triggers registration at module-load time::

    from extensions.context_providers import from_config  # noqa: F401

The builder returns ``None`` when no YAML file is found, so importing the
module is safe in projects that don't provide the file.

Tags
----
``config``
"""

from __future__ import annotations

import os
from pathlib import Path

from cloudagent_ext.context_system.section_registry import (
    SectionScope,
    register_section,
)

__all__: list[str] = []

# ---------------------------------------------------------------------------
# Attempt to import yaml — it's an optional dependency for the from_config
# provider specifically (the other providers don't need it).
# ---------------------------------------------------------------------------
try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None  # type: ignore[assignment]


def _read_sections_from_yaml(cwd: str) -> list[dict[str, str]] | None:
    """Read declared sections from ``.cloudagent/context_sections.yaml``.

    Returns a list of ``{"title": …, "content": …}`` dicts, or ``None``
    if the file does not exist or is malformed.
    """
    if _yaml is None:
        return None

    yaml_path = Path(cwd) / ".cloudagent" / "context_sections.yaml"
    if not yaml_path.is_file():
        return None

    try:
        raw = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(raw, dict):
        return None
    sections = raw.get("sections", [])
    if not isinstance(sections, list):
        return None
    return [
        {"title": str(s.get("title", "")), "content": str(s.get("content", ""))}
        for s in sections
        if isinstance(s, dict) and s.get("content")
    ]


def _config_sections_builder(runtime_ctx: dict) -> str | None:
    """Build the declared-config section block.

    Tries, in order:
    1. ``.cloudagent/context_sections.yaml`` relative to ``runtime_ctx["cwd"]``.
    2. ``runtime_ctx["custom"]["declared_sections"]`` as a fallback override.

    Returns ``None`` when no sections are found.
    """
    sections: list[dict[str, str]] | None = None

    # Strategy 1: read from YAML file on disk.
    cwd = runtime_ctx.get("cwd") or os.getcwd()
    sections = _read_sections_from_yaml(cwd)

    # Strategy 2: runtime_ctx override (useful for tests / in-memory injection).
    if not sections:
        custom = runtime_ctx.get("custom", {})
        custom_sections = custom.get("declared_sections")
        if isinstance(custom_sections, list) and custom_sections:
            sections = custom_sections

    if not sections:
        return None

    blocks: list[str] = []
    for s in sections:
        title = (s.get("title") or "").strip()
        content = (s.get("content") or "").strip()
        if not content:
            continue
        if title:
            if "#" in title:
                blocks.append(f"{title}\n{content}")
            else:
                blocks.append(f"## {title}\n{content}")
        else:
            blocks.append(content)

    return "\n\n".join(blocks) if blocks else None


register_section(
    "declared-config",
    builder=_config_sections_builder,
    order=57,
    cache_scope=SectionScope.SESSION,
    tags=["config"],
)
