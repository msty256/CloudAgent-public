"""src/services/feature_gate/decorators.py — re-export from canonical Layer 1."""

from __future__ import annotations

from cloudagent_ext.feature_gate.decorators import (  # noqa: F401
    feature_gated,
    feature_gated_class,
    guarded_call,
    guarded_is_enabled,
)
