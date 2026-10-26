#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""OAuth services package.
Real OAuth flow lives in ``src/auth/oauth.py``; this package holds the
service-layer helpers (``client.get_organization_uuid``, etc.) that
"""

from cloudagent_ext.services.oauth.client import get_organization_uuid

__all__ = ["get_organization_uuid"]
