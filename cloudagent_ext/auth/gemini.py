#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Gemini API key authentication."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class GeminiAuth:
    """Gemini API key authentication handler."""

    def load_api_key(self) -> str | None:
        """Load Gemini API key from environment or config."""
        # Env vars
        for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            key = os.environ.get(var)
            if key:
                return key

        # Config
        try:
            from cloudagent_ext.config import load_config

            config = load_config()
            key = config.get("providers", {}).get("gemini", {}).get("api_key", "")
            if key:
                return key
        except Exception:  # nosec B110
            pass  # Intentional best-effort path; the surrounding fallback remains valid.

        return None

    def is_configured(self) -> bool:
        """Check if a Gemini API key is available."""
        return self.load_api_key() is not None
