#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``cloudagent forecast`` CLI subcommand."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from cloudagent_ext.cli.subcommand_registry import register  # pylint: disable=no-name-in-module
from cloudagent_ext.intent_forecast.config import load_intent_forecast_config
from cloudagent_ext.intent_forecast.learning import record_feedback, read_recent_feedback
from cloudagent_ext.intent_forecast.messages import (
    format_forecast_for_display,
    parse_selection,
    result_to_dict,
)
from cloudagent_ext.intent_forecast.persistence import (
    load_latest_forecast,
    read_forecast_history,
    save_forecast_result,
)
from cloudagent_ext.intent_forecast.service import IntentForecastService
from cloudagent_ext.session_intelligence.queue import enqueue_summary_job
from cloudagent_ext.session_intelligence.summarizer import summarize_session

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloudagent forecast")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "status", "accept", "dismiss", "summarize", "stats"],
    )
    parser.add_argument("target", nargs="?", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--session", default="")
    parser.add_argument("--pending", action="store_true", help="process pending summary queue")
    return parser


@register("forecast")
def run_forecast_command(args: list[str]) -> int:
    parser = _build_parser()
    ns = parser.parse_args(args)
    cwd = Path.cwd()
    cfg = load_intent_forecast_config(cwd=cwd)

    if ns.command == "status":
        payload = {
            "enabled": cfg.enabled,
            "auto_display": cfg.auto_display,
            "idle_seconds": cfg.idle_seconds,
            "feedback_events": len(read_recent_feedback(limit=100)),
            "forecast_records": len(read_forecast_history(limit=100, cwd=cwd)),
        }
        _print(payload, ns.json)
        return 0
    if ns.command == "stats":
        rows = read_recent_feedback(limit=200)
        counts: dict[str, int] = {}
        for row in rows:
            event = str(row.get("event") or "")
            counts[event] = counts.get(event, 0) + 1
        _print({"events": counts, "recent": rows[-10:]}, ns.json)
        return 0
    if ns.command == "accept":
        result = load_latest_forecast(cwd=cwd)
        if result is None:
            print("No saved forecast suggestion is available to accept.", file=sys.stderr)
            return 1
        suggestion = parse_selection(ns.target or "1", result.suggestions)
        if suggestion is None:
            print(f"No forecast suggestion matches {ns.target!r}.", file=sys.stderr)
            return 1
        if cfg.feedback_enabled:
            record_feedback(
                "accepted_started",
                suggestion=suggestion,
                cwd=cwd,
                fingerprint=result.fingerprint,
            )
        if ns.json:
            print(
                json.dumps(
                    {"prompt": suggestion.prompt, "suggestion_id": suggestion.id},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(suggestion.prompt)
        return 0
    if ns.command == "dismiss":
        print("Forecast dismissed.")
        return 0
    if ns.command == "summarize":
        if ns.pending:
            from cloudagent_ext.session_intelligence.queue import process_pending_summary_jobs

            _print(process_pending_summary_jobs(), ns.json)
            return 0
        if not ns.session:
            print(
                "usage: cloudagent forecast summarize --session <session_id> [--pending]",
                file=sys.stderr,
            )
            return 2
        result = summarize_session(ns.session)
        _print(result, ns.json)
        return 0

    result = IntentForecastService(
        conversation=None,
        provider=None,
        model=None,
        workspace_root=cwd,
        config=cfg,
    ).generate(trigger="cli", force=True)
    if cfg.summary_lazy_generate:
        for suggestion in result.suggestions[:1]:
            del suggestion
            try:
                enqueue_summary_job("latest", cwd=cwd)
            except Exception:
                logger.debug("Failed to enqueue lazy summary", exc_info=True)
            break
    if ns.json:
        print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
    else:
        print(format_forecast_for_display(result))
    save_forecast_result(result, trigger="cli", cwd=cwd)
    if cfg.feedback_enabled and not result.generated:
        record_feedback("empty", cwd=cwd, fingerprint=result.fingerprint)
    return 0


def _print(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
