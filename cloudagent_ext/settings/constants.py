"""Default settings values matching TypeScript."""

from __future__ import annotations

from .types import (
    CompactSettings,
    HookSettings,
    OutputStyleSettings,
    PermissionsConfig,
    SettingsSchema,
)

DEFAULT_SETTINGS = SettingsSchema(
    model="claude-sonnet-4-20250514",
    small_fast_model="claude-3-5-haiku-20241022",
    provider="anthropic",
    # F-47: top-level permission_mode left as "" (the new back-compat default).
    # The actual default mode for new binaries is `default`; if a user wants
    # to start in a non-default mode, they set ``permissions.defaultMode``
    # (preferred) or this top-level field (legacy).
    permission_mode="",
    # F-47: structured permissions block — empty default keeps the binary
    # in ``default`` mode with no allow/deny rules and bypass disabled.
    permissions=PermissionsConfig(),
    tools={},
    output_style=OutputStyleSettings(
        style="default",
        max_width=120,
        show_thinking=False,
    ),
    compact=CompactSettings(
        auto_compact=True,
        threshold_tokens=100_000,
        max_compact_retries=3,
    ),
    hooks=HookSettings(
        enabled=True,
        timeout_ms=30_000,
        max_concurrent=5,
    ),
    mcp_servers={},
    max_turns=0,
    max_cost_usd=0.0,
    effort="",
    plan_mode=False,
    non_interactive=False,
    custom_system_prompt="",
    append_system_prompt="",
    allowed_tools=[],
    denied_tools=[],
    fast_mode=False,
    session_retention_days=30,
)

# Known valid effort values. ``xhigh`` is a real Claude effort level
# (between high and max) but only some models accept it on the wire —
# resolve_thinking_effort (src/query/query.py) clamps it to "high" on
# models that reject it (probed 2026-07-18: opus-4-8 accepts; sonnet-4-6
# and opus-4-6 return 400 "does not support effort level 'xhigh'").
VALID_EFFORT_VALUES = ("", "low", "medium", "high", "xhigh", "max")

# Known valid output styles
# OS-1: the VALID_OUTPUT_STYLES enum was removed — it was invented (rejected
# the real builtin "explanatory", accepted three nonexistent styles). Style
# names are free-form ( z.string()); the loader's available_output_styles()
# is the runtime truth where a listing is needed.

# Known valid spinner-verb merge modes 
VALID_SPINNER_VERB_MODES = ("append", "replace")

# Known valid permission modes
VALID_PERMISSION_MODES = (
    "default",
    "plan",
    "acceptEdits",
    "bypassPermissions",
    "dontAsk",
)
