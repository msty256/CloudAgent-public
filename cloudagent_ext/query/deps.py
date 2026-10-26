#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable
from uuid import uuid4


@dataclass
class QueryDeps:
    call_model: Callable[..., AsyncGenerator[Any, None]]
    uuid: Callable[[], str] = field(default_factory=lambda: lambda: uuid4().hex)
