# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Compatibility cache API backed by canonical catalog invalidation.

The extension layer no longer owns TTL discovery or registry caches. Legacy
callers may retain their imports, but reads deliberately miss and every clear or
invalidation is forwarded to cloudagent_ext.skills.invalidate_skill_catalog.
"""

from __future__ import annotations


import logging
import time
from typing import Any, Generic, TypeVar

from cloudagent_ext.skills.catalog import invalidate_skill_catalog

T = TypeVar("T")
logger = logging.getLogger(__name__)


class CacheEntry(Generic[T]):
    """Legacy value object retained for import compatibility."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: T, ttl_seconds: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl_seconds

    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


class SkillCache:
    """Stateless facade over canonical skill-catalog invalidation.

    set and get remain callable for older integrations, but values are never
    retained. This prevents an extension-local result from outliving the
    workspace-scoped catalog snapshot.
    """

    __slots__ = ("default_ttl", "_label")

    def __init__(
        self,
        default_ttl: float = 300.0,
        *,
        label: str = "legacy",
    ) -> None:
        self.default_ttl = default_ttl
        self._label = label

    def get(self, key: str) -> Any | None:
        """Always miss because discovery results belong to the catalog."""

        logger.debug("[skills_ext] ignored legacy %s cache get: %s", self._label, key)

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Accept but do not retain a legacy cache value."""

        del value, ttl
        logger.debug("[skills_ext] ignored legacy %s cache set: %s", self._label, key)

    def invalidate(self, key: str) -> None:
        """Invalidate the canonical catalog."""

        invalidate_skill_catalog(f"skills_ext {self._label} cache key invalidated: {key}")

    def clear(self) -> None:
        """Invalidate all canonical skill views."""

        invalidate_skill_catalog(f"skills_ext {self._label} cache cleared")

    def cleanup_expired(self) -> int:
        """Return zero because this facade owns no entries."""

        return 0


_catalog_cache_facade = SkillCache(label="catalog")


def get_discovery_cache() -> SkillCache:
    """Return the stateless canonical-catalog compatibility facade."""

    return _catalog_cache_facade


def get_registry_cache() -> SkillCache:
    """Return the same canonical-catalog compatibility facade."""

    return _catalog_cache_facade


def clear_all_caches() -> None:
    """Invalidate the canonical catalog and all dependent skill views."""

    invalidate_skill_catalog("skills_ext clear_all_caches")
