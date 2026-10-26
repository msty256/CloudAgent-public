# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Worker subprocess entry point.

Run with::

    python -m extensions.daemon.worker_main <kind>

The supervisor spawns workers through this module so the worker
process is a *clean* Python subprocess — no CLI dispatch overhead,
no TUI imports, no argparser. The worker reads its configuration
from the inherited environment (the supervisor injects
``CLOUDAGENT_DAEMON_*`` vars).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Sequence

from extensions.daemon.errors import PermanentWorkerError, UnknownWorkerKindError
from extensions.daemon.worker_registry import WorkerRegistry

# Eager registration: importing this module should make every
# built-in worker factory discoverable.
import extensions.daemon.workers  # noqa: F401  (registers on import)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


async def _run_worker(kind: str) -> int:
    try:
        worker = WorkerRegistry.create(kind)
    except UnknownWorkerKindError:
        print(
            f"worker_main: unknown worker kind {kind!r}; known: {WorkerRegistry.known_kinds()}",
            file=sys.stderr,
        )
        return 78

    env = dict(__import__("os").environ)
    try:
        return await worker.run(env)
    except PermanentWorkerError as exc:
        logging.error("worker_main: permanent error: %s", exc)
        return 78
    except asyncio.CancelledError:
        return 0
    except Exception:
        logging.exception("worker_main: unhandled exception")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    if len(argv) < 2 or not argv[1]:
        print(
            "usage: python -m extensions.daemon.worker_main <kind>",
            file=sys.stderr,
        )
        return 78
    _configure_logging()
    kind = argv[1]
    return asyncio.run(_run_worker(kind))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
