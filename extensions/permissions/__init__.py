# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""CloudAgent permissions extensions."""

from .perms_reader import settings_perms, settings_perms_structured_is_explicit

__all__ = [
    "settings_perms",
    "settings_perms_structured_is_explicit",
]
