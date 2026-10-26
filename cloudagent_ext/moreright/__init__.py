"""Package placeholder for the `moreright` subsystem."""

from __future__ import annotations

import json
from pathlib import Path

SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent / 'reference_data' / 'subsystems' / 'moreright.json'
)
_SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text())

ARCHIVE_NAME = _SNAPSHOT['archive_name']
MODULE_COUNT = _SNAPSHOT['module_count']
SAMPLE_FILES = tuple(_SNAPSHOT['sample_files'])
PORTING_NOTE = f"Package placeholder for '{ARCHIVE_NAME}' ({MODULE_COUNT} module references)."

__all__ = ['ARCHIVE_NAME', 'MODULE_COUNT', 'PORTING_NOTE', 'SAMPLE_FILES']
