# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""二开 agent extensions."""

from .session_persist import load_from_session_storage, save_to_session_storage

__all__ = [
    "load_from_session_storage",
    "save_to_session_storage",
]
