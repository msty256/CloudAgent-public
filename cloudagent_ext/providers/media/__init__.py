#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Media generation providers — image and video generation.

Architecture::

    media/
        __init__.py          ← exports
        base.py              ← MediaProvider / ImageProvider / VideoProvider ABCs
        registry.py          ← MediaProviderRegistry + media_registry singleton
        image/
            __init__.py
            agnes.py         ← AgnesImageProvider
        video/
            __init__.py
            agnes.py         ← AgnesVideoProvider

New providers are registered by importing the registry and calling
``media_registry.register_image(...)`` or
``media_registry.register_video(...)`` at module level (same pattern as
``register_provider(...)`` in ``cloudagent_ext/providers/__init__.py``).
"""

from cloudagent_ext.providers.media.base import (
    ImageProvider,
    ImageResult,
    MediaProvider,
    VideoProvider,
    VideoResult,
    VideoStatus,
    VideoTask,
)
from cloudagent_ext.providers.media.registry import MediaProviderRegistry, media_registry

__all__ = [
    # Base classes
    "ImageProvider",
    "ImageResult",
    "MediaProvider",
    "VideoProvider",
    "VideoResult",
    "VideoStatus",
    "VideoTask",
    # Registry
    "MediaProviderRegistry",
    "media_registry",
]
