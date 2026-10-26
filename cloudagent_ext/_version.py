#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Static semantic version, hand-bumped on release.

``BASE_VERSION`` below is the single source of truth for the package
version. Bump it by hand when cutting a release, following SemVer:

    MAJOR -- incompatible API changes
    MINOR -- backwards-compatible functionality
    PATCH -- backwards-compatible bug fixes

Usage
-----
    from cloudagent_ext._version import __version__

Package metadata (``pyproject.toml``) reads this attribute via
``tool.setuptools.dynamic.version.attr`` so that ``pip install`` and
``python -m build`` embed the same value, and
``cloudagent_ext.__version__`` resolves to it at runtime (see
``cloudagent_ext/__init__.py::_resolve_version``).

Note: this used to be a date-based CalVer (``YYYY.M.D``). It was replaced
by a hand-bumped SemVer so releases carry a meaningful, monotonic version
number instead of a build date. There is intentionally no ``.devN``
suffix and no git-tag derivation — keep the version string clean.
"""

BASE_VERSION = "1.2.1"


def _parse_version(raw: str) -> tuple[int, ...]:
    """Validate ``BASE_VERSION`` and return it as a numeric tuple.

    Fails loudly at import time with an actionable message, because
    ``BASE_VERSION`` is hand-edited — a typo like ``"1.2.x"`` would
    otherwise surface much later as a cryptic ``int()`` error deep in
    packaging or CLI code.
    """
    parts = raw.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(
            f"BASE_VERSION {raw!r} is not a valid semantic version; "
            "expected MAJOR.MINOR.PATCH with numeric parts (e.g. '1.2.3')."
        )
    return tuple(int(p) for p in parts)


__version__ = BASE_VERSION
__version_info__ = _parse_version(__version__)
