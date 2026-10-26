#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Rule-based single-slot scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from cloudagent_ext.capabilities.multimodel_protocol import MultiModelResult  # pylint: disable=no-name-in-module
from cloudagent_ext.providers.base import MessageInput

from .base import MultiModelStrategyBase

RouteMatcher = Callable[[list[MessageInput], Any], str]


@dataclass(frozen=True)
class RoutingRule:
    """A matcher which returns the slot name to use for a turn."""

    matcher: RouteMatcher
    description: str = ""


@dataclass
class RoutingStrategy(MultiModelStrategyBase):
    """Choose one enabled provider using the first matching routing rule."""

    rules: list[RoutingRule] = field(default_factory=list)
    fallback_slot: str = "default"
    name = "routing"

    async def execute(self, router: Any, messages: list[MessageInput], **kwargs: Any) -> list[MultiModelResult]:
        slots = [slot for slot in router.slots if slot.enabled]
        if not slots:
            return []
        context = kwargs.get("tool_context")
        selected_name: str | None = None
        for rule in self.rules:
            try:
                selected_name = rule.matcher(messages, context)
            except Exception:
                continue
            if selected_name:
                break
        selected_name = selected_name or self.fallback_slot
        slot = next((item for item in slots if item.name == selected_name), slots[0])
        return [await router._call_slot(slot, messages, **kwargs)]

    def install_hook(self) -> None:
        """Register a traceable pre-LLM hook without mutating query internals.

        Actual selection happens in ``execute`` because this hook API only
        transforms messages/system prompts and cannot safely replace provider.
        """
        from cloudagent_ext.query.hook_registry import register_loop_hook

        register_loop_hook("multimodel_routing", self._routing_hook, "pre_llm", priority=50)

    def _routing_hook(self, messages: Any, system_prompt: Any, **_kwargs: Any) -> tuple[Any, Any]:
        return messages, system_prompt
