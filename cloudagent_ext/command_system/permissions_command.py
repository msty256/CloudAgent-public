"""permissions — interactive ``/permissions`` command (port of TS local-jsx).

Reference command for the P0-3 interactive-command bridge (see
my-docs/get-parity-by-folder/commands-phase2-interactive-bridge-plan.md): a
single ``select`` over the user-facing permission modes, backed by the reactive
``AppState.permission_mode`` field (``src/state/app_state.py``) and its
persistence handler ``_on_permission_mode_change`` (which notifies the CCR
bridge / SDK status stream).

It demonstrates the keystone win: **one** command body drives the REPL numbered
menu *and* the Textual modal through the ``UIHost`` port — no per-surface
implementation. Chosen over ``/effort`` because its backing state genuinely
exists/persists and it has no ``open_dialog`` intercept in the TUI, so the
registry → ``TextualUIHost`` path is reachable on both surfaces.

(The existing ``tui/screens/permission_modal.py`` is the per-tool permission
*request* y/n prompt — a different concern, no collision.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cloudagent_ext.permissions.cycle import CYCLE_ORDER

from .types import (
    CommandContext,
    InteractiveCommand,
    InteractiveOutcome,
    UIOption,
)

# Options are generated from ``cycle.CYCLE_ORDER`` so the picker, the Shift+Tab
# cycle and ``--permission-mode`` cannot drift apart again (they used to carry
# three different sets).
#
# Historical note: this list used to exclude ``dontAsk`` as an "internal mode —
# not user-addressable". That claim was already false (`--permission-mode
# dontAsk` has always been accepted and honoured, see
# `permissions/modes.py::initial_permission_mode_from_cli`), and `cycle.py`
# documented `dontAsk` as part of the interactive cycle. It is listed now so
# the two surfaces agree. `bubble` remains internal: it is the sub-agent
# permission-escalation mode and no entry point accepts it.
_MODE_DESCRIPTIONS: dict[str, str] = {
    "default": "Prompt before each tool's first use",
    "acceptEdits": "Auto-accept file edits in the workspace",
    "plan": "Plan only — no edits or commands",
    "dontAsk": "Deny anything that requires approval instead of prompting",
    "auto": "Automatically classify and allow safe commands",
    "bypassPermissions": "Skip all permission prompts",
}

_PERMISSION_MODE_OPTIONS: list[UIOption] = [
    UIOption(
        value=mode,
        label=mode,
        description=_MODE_DESCRIPTIONS[mode],
    )
    for mode in CYCLE_ORDER
]


@dataclass(frozen=True)
class PermissionsCommand(InteractiveCommand):
    """Select-one-of the user-facing permission modes; persist via the
    reactive AppState store. Frozen + no new fields (the ``StatuslineCommand``
    pattern); behavior lives entirely in :meth:`run`.
    """

    async def run(self, args: str, context: CommandContext) -> InteractiveOutcome:
        store: Any = context.app_state_store

        current: str | None = None
        if store is not None:
            try:
                current = store.get_state().permission_mode
            except Exception:
                current = None

        # The single select — same call drives REPL menu and TUI modal.
        pick = await context.ui.select(
            "Permission mode",
            _PERMISSION_MODE_OPTIONS,
            current=current,
        )
        if pick is None:
            # Cancelled — no output (display == 'skip').
            return InteractiveOutcome.skip()

        if store is None:
            # No reactive store wired on this surface — report rather than
            # silently no-op (mirrors the honest-failure stance of NullUIHost).
            return InteractiveOutcome(
                message="Permission mode unavailable (no app state store).",
                display="system",
            )

        if pick == current:
            return InteractiveOutcome(
                message=f"Permission mode unchanged ({pick}).",
                display="system",
            )

        # Persist: set_state fires on_change -> _on_permission_mode_change,
        # which notifies the CCR bridge / SDK status stream.
        from cloudagent_ext.state.app_state import replace_state

        store.set_state(lambda s: replace_state(s, permission_mode=pick))
        return InteractiveOutcome(
            message=f"Permission mode set to {pick}.",
            display="system",
        )


PERMISSIONS_COMMAND = PermissionsCommand(
    name="permissions",
    description="Switch the tool permission mode",
    # Security-sensitive: it can select ``bypassPermissions``. Keep it
    # user-driven only so a future model→slash-command path can never let
    # the model escalate its own permissions. (TS treats permission/config
    # mutation as user-initiated.)
    disable_model_invocation=True,
)


__all__ = ["PERMISSIONS_COMMAND", "PermissionsCommand"]
