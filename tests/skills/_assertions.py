#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Assertions shared by migrated skill invocation tests."""

from __future__ import annotations

from typing import Any


def rendered_prompt(result: Any) -> str:
    """Return the prompt injected by either model or user skill invocation."""

    output = result.output
    if isinstance(output, dict) and isinstance(output.get("prompt"), str):
        return output["prompt"]

    messages = result.new_messages
    assert messages, f"skill invocation did not inject a prompt: {output!r}"
    content = messages[-1].content
    assert isinstance(content, str), f"skill prompt is not text: {content!r}"
    metadata, separator, prompt = content.partition("\n\n")
    assert separator and metadata.startswith("<command-message>"), f"skill prompt metadata is malformed: {content!r}"
    return prompt
