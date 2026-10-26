# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Per-stage provider/model routing for orchestrator execution modes."""

from extensions.orchestrator.contracts.provider_routing import (
    ProviderRouter,
    RoutingSnapshot,
    StageModel,
    StageProvider,
)

from .config import ProviderRoutingConfig, normalize_stage_overrides
from .factory import build_provider_router, stage_id_from_run_kind
from .router import ProviderReference, ProviderRoute, StaticProviderRouter, provider_name

__all__ = [
    "ProviderReference",
    "ProviderRoute",
    "ProviderRouter",
    "ProviderRoutingConfig",
    "RoutingSnapshot",
    "StageModel",
    "StageProvider",
    "StaticProviderRouter",
    "build_provider_router",
    "normalize_stage_overrides",
    "provider_name",
    "stage_id_from_run_kind",
]
