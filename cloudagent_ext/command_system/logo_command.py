"""logo — interactive ``/logo`` command (port of local-jsx).
startup-banner color palette and persists it to the global config ``logoColor`` key;
the Ink TUI banner resolves and renders it — live on
selection, and again at every startup via its synchronous config read.
Coexistence: the interactive Ink TUI **shadows** ``/logo`` with its own local
command + picker overlay ( →
), which persists through the agent-server ``set_logo_color``
control. This ``InteractiveCommand`` therefore serves the non-TUI surfaces via the
``UIHost`` port — headless/SDK (``NullUIHost`` → clean error) and the
help/aggregator listings. (Its original REPL/Textual consumers were deleted in the
UI consolidation, PR #566.)
Faithfulness to:
  * ``call(onDone, _context)`` **ignores args** — the picker is the only path; no
    headless keystone (on ``NullUIHost`` the ``select`` raises → engine clean error).
  * **Success → ``display="user"``** ( ``onDone("Startup logo set to …")`` with no
    options → model-visible ``createUserMessage``).
  * **Cancel → "Logo picker dismissed" / ``display="system"``** (verbatim ).
Deliberate divergences (documented for parity review):
  * **No swatch preview** in the picker — ``LogoPicker`` shows an ANSI gradient
    swatch per option, but the ``select`` primitive has plain labels. Labels are the
    friendly ``LOGO_PALETTE_LABELS`` ( shows labels too).
  * **Static description** ("Change the startup logo color scheme"); 's is dynamic
    ``…(current: {label})`` — a frozen ``CommandBase.description`` can't be a getter.
    The current palette is the picker's ``current=`` marker.
  * **Persist via config ``logoColor``** (top-level key, like ``/theme``).
``logo_palettes`` / ``set_logo_color`` are imported lazily (the ``theme``/``app.py``
discipline).
"""
from __future__ import annotations

from dataclasses import dataclass

from .types import (
    CommandContext,
    InteractiveCommand,
    InteractiveOutcome,
    UIOption,
)


def _current_logo() -> str:
    """The persisted palette name, or the default — mirrors /
     (validate via ``is_logo_palette_name``)."""
    from cloudagent_ext.config import load_config
    from cloudagent_ext.utils.logo_palettes import DEFAULT_LOGO_PALETTE, is_logo_palette_name

    current = load_config().get("logoColor")
    return current if is_logo_palette_name(current) else DEFAULT_LOGO_PALETTE


def _logo_options(current: str) -> list[UIOption]:
    """Picker options: friendly labels, marking the current palette. Lazy import."""
    from cloudagent_ext.utils.logo_palettes import LOGO_PALETTE_LABELS, LOGO_PALETTE_NAMES

    return [
        UIOption(
            value=name,
            label=LOGO_PALETTE_LABELS[name],
            description="current" if name == current else None,
        )
        for name in LOGO_PALETTE_NAMES
    ]


@dataclass(frozen=True)
class LogoCommand(InteractiveCommand):
    """Pick the startup logo color palette and persist it. Frozen + no new fields
    (the ``ThemeCommand`` pattern); behavior lives in:meth:`run`."""

    async def run(self, args: str, context: CommandContext) -> InteractiveOutcome:
        # call ignores args — the picker is the only path. No headless keystone;
        # on NullUIHost the select below raises -> the engine returns a clean error.
        from cloudagent_ext.config import set_logo_color
        from cloudagent_ext.utils.logo_palettes import LOGO_PALETTE_LABELS

        current = _current_logo()
        picked = await context.ui.select(
            "Select startup logo color:", _logo_options(current), current=current
        )
        if picked is None:
            # cancel: onDone("Logo picker dismissed", {display:"system"}).
            return InteractiveOutcome(message="Logo picker dismissed", display="system")
        set_logo_color(picked)  # persist (TS saveGlobalConfig logoColor)
        # success: onDone("Startup logo set to …") with NO options => model-visible.
        return InteractiveOutcome(
            message=f"Startup logo set to {LOGO_PALETTE_LABELS[picked]}. Visible on next launch.",
            display="user",
        )


LOGO_COMMAND = LogoCommand(
    name="logo",
    description="Change the startup logo color scheme",  # static (TS dynamic — see docstring)
)


__all__ = ["LOGO_COMMAND", "LogoCommand"]
