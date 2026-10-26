#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Minimal template picker helpers.

The full interactive picker can grow on top of this adapter; for now it
exposes the same catalogue ordering that the TUI can render in a select list.
"""

from __future__ import annotations

from dataclasses import dataclass

from cloudagent_ext.services.templates import (
    TemplateCatalogue,
    TemplateKind,
    TemplateRegistry,
    get_manifest,
)


@dataclass(frozen=True)
class TemplatePickerItem:
    id: str
    label: str
    description: str
    kind: TemplateKind


def build_template_picker_items(
    registry: TemplateRegistry,
    *,
    kind: TemplateKind | None = None,
) -> list[TemplatePickerItem]:
    catalogue = TemplateCatalogue(registry)
    items: list[TemplatePickerItem] = []
    for template in catalogue.list(kind=kind):
        manifest = get_manifest(template)
        items.append(
            TemplatePickerItem(
                id=template.id,
                label=template.title,
                description=template.description or "",
                kind=manifest.kind,
            )
        )
    return items


__all__ = ["TemplatePickerItem", "build_template_picker_items"]
