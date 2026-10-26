#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Fixed-capacity UUID dedup set with FIFO eviction.
The CCR bridge has an echo problem: a message a client posts may be
re-delivered on the read stream, and a transport swap can cause the
server to replay history. Two parallel sets at capacity 2000 act as the
dedup buffer (one for posted UUIDs, one for inbound UUIDs).
O(1) ``add``/``has``/``len``; O(capacity) memory. The code uses a
manual ``writeIdx`` modulo because JS lacks a deque; Python's
``collections.deque(maxlen=capacity)`` provides FIFO eviction natively.
Concurrency: single-coroutine use only. Concurrent ``add``/``has``/``clear``
calls from different asyncio tasks are undefined behavior. The source
is single-threaded JS by definition; Python needs this said explicitly
because asyncio + threads is a footgun.
Originally lived at
``src/bridge/bounded_uuid_set.py``; moved to ``cloudagent_ext/`` during the single-layering
refactor. The ``src/`` compatibility facade was removed along with it,
so import the ``cloudagent_ext`` path directly.
"""

from __future__ import annotations

from collections import deque

DEFAULT_CAPACITY = 2000


class BoundedUUIDSet:
    """FIFO-bounded set; oldest entry evicted when capacity is reached."""

    __slots__ = ("_capacity", "_ring", "_set")

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity <= 0:
            raise ValueError("BoundedUUIDSet capacity must be > 0")
        self._capacity: int = capacity
        # ``deque(maxlen=N)`` automatically discards the leftmost element
        # when ``append`` would exceed ``N``. We mirror that eviction in
        # ``_set`` so membership stays consistent.
        self._ring: deque[str] = deque(maxlen=capacity)
        self._set: set[str] = set()

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        return len(self._set)

    def add(self, uuid: str) -> None:
        """Add ``uuid``; idempotent (does NOT bump LRU position).
        """
        if uuid in self._set:
            return
        if len(self._ring) == self._capacity:
            # deque.append will evict leftmost; remove it from the set
            # FIRST so we don't leak it.
            evicted = self._ring[0]
            self._set.discard(evicted)
        self._ring.append(uuid)
        self._set.add(uuid)

    def has(self, uuid: str) -> bool:
        return uuid in self._set

    def __contains__(self, uuid: object) -> bool:
        return isinstance(uuid, str) and uuid in self._set

    def clear(self) -> None:
        self._ring.clear()
        self._set.clear()


__all__ = ["DEFAULT_CAPACITY", "BoundedUUIDSet"]
