# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""context_providers — Layer 2 reference context providers.

Three reference implementations demonstrating the ``register_section`` API
for injecting dynamic context into the system prompt:

* ``from_issue`` — Issue-tracker context (order=55, tags: workflow/issue-tracker)
* ``from_ci`` — CI pipeline status (order=56, tags: ci)
* ``from_config`` — Declarative YAML-snippet injection (order=57, tags: config)

Importing any of these modules triggers `register_section` at module-load
time — there is no separate "install" step.
"""

from __future__ import annotations

__all__ = [
    "from_ci",
    "from_config",
    "from_issue",
]
