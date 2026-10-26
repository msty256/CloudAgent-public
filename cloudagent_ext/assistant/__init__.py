"""Package placeholder for the `assistant` subsystem."""

from __future__ import annotations

import json
from pathlib import Path

from cloudagent_ext.assistant.session_chooser import AssistantSessionChooser
from cloudagent_ext.assistant.session_history import (
    HISTORY_PAGE_SIZE,
    HistoryAuthCtx,
    HistoryPage,
    create_history_auth_ctx,
    fetch_latest_events,
    fetch_older_events,
)

SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent / 'reference_data' / 'subsystems' / 'assistant.json'
)
_SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text())

ARCHIVE_NAME = _SNAPSHOT['archive_name']
MODULE_COUNT = _SNAPSHOT['module_count']
SAMPLE_FILES = tuple(_SNAPSHOT['sample_files'])
PORTING_NOTE = f"Package placeholder for '{ARCHIVE_NAME}' ({MODULE_COUNT} module references)."

__all__ = [
    'ARCHIVE_NAME',
    'AssistantSessionChooser',
    'HISTORY_PAGE_SIZE',
    'HistoryAuthCtx',
    'HistoryPage',
    'MODULE_COUNT',
    'PORTING_NOTE',
    'SAMPLE_FILES',
    'create_history_auth_ctx',
    'fetch_latest_events',
    'fetch_older_events',
]
