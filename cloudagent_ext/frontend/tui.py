#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""TUI frontend plugin for the downstream registry."""

from __future__ import annotations
# pylint: disable=E0611

from cloudagent_ext.frontend.protocol import FrontendPlugin
from cloudagent_ext.frontend.registry import register_frontend


@register_frontend
class TUIFrontend(FrontendPlugin):
    name = "tui"
    display_name = "Textual TUI"

    def run(self, ctx, argv: list[str]) -> int:
        from cloudagent_ext.entrypoints.tui import TUIOptions

        from cloudagent_ext.tui.entrypoint import run_tui

        options = TUIOptions(
            provider_name=ctx.provider_name,
            model=ctx.options.model,
            max_turns=ctx.options.max_turns,
            allowed_tools=ctx.options.allowed_tools,
            disallowed_tools=ctx.options.disallowed_tools,
            stream=True,
            permission_mode=ctx.options.permission_mode,
            is_bypass_permissions_mode_available=ctx.options.is_bypass_permissions_mode_available,
            workspace_root=ctx.workspace_root,
            append_system_prompt=ctx.options.append_system_prompt,
        )
        return run_tui(
            options,
            provider=ctx.provider,
            session=ctx.session,
            tool_registry=ctx.tool_registry,
            tool_context=ctx.tool_context,
            runtime_context=ctx,
            resume_session_id=ctx.options.resume_session_id,
            resume_browse=ctx.options.resume_browse,
        )
