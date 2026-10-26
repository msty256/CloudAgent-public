#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Model system extensions — model config registry and discovery hooks.

Provides a ``register_model_config()`` API (mirroring
``cloudagent_ext/providers/factory.py``) so that downstream extensions
can add or override model configurations without modifying
``src/models/configs.py``.

Usage::

    from cloudagent_ext.models import register_model_config
    from cloudagent_ext.models.configs import ModelConfig

    register_model_config(
        "my-custom-model",
        ModelConfig(
            model_id="my-custom-model",
            display_name="My Custom Model",
            context_window=128_000,
            max_output_tokens=8_192,
            ...
        ),
    )

All registered configs are merged into ``src.models.configs.MODEL_CONFIGS``
when this module is imported.
"""

from __future__ import annotations

from typing import Optional

from cloudagent_ext.models.configs import ModelConfig, MODEL_CONFIGS


# ---------------------------------------------------------------------------
# Extension registry
# ---------------------------------------------------------------------------

_EXTRA_MODEL_CONFIGS: dict[str, ModelConfig] = {}


def register_model_config(model_id: str, config: ModelConfig) -> None:
    """Register an additional model configuration.

    Idempotent: calling twice with the same *model_id* is a no-op
    (first registration wins).
    """
    if model_id not in _EXTRA_MODEL_CONFIGS and model_id not in MODEL_CONFIGS:
        _EXTRA_MODEL_CONFIGS[model_id] = config
        MODEL_CONFIGS[model_id] = config


def get_extra_model_config(model_id: str) -> Optional[ModelConfig]:
    """Look up an extra model configuration by id."""
    return _EXTRA_MODEL_CONFIGS.get(model_id)


def list_extra_models() -> list[str]:
    """Return the list of model IDs registered via ``register_model_config``."""
    return list(_EXTRA_MODEL_CONFIGS.keys())


# ---------------------------------------------------------------------------
# Side-effect: register extended model configs on import
# ---------------------------------------------------------------------------
from cloudagent_ext.models.configs import EXTRA_MODEL_CONFIGS  # noqa: E402, F811

for _model_id, _config in EXTRA_MODEL_CONFIGS.items():
    register_model_config(_model_id, _config)


__all__ = [
    "register_model_config",
    "get_extra_model_config",
    "list_extra_models",
    "ModelConfig",
]
