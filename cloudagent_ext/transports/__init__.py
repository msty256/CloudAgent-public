"""Wire-level transports + protocol-layer helpers for SDK sessions.
This package collects everything that lives under
 plus the small ``RemoteIO``
protocol-layer bridge (placed
here because Python keeps sync ``cli_core`` separate from async
transports — see ``my-docs/get-parity-by-folder/cli-gap-analysis.md``
§2.5).
Public surface:
*:class:`WebSocketTransport` — reconnecting WS read/write.
*:class:`HybridTransport` — WS read + HTTP POST write (via
  :class:`SerialBatchEventUploader`).
*:class:`SSETransport` — SSE read + HTTP POST write (CCR v2).
*:class:`SerialBatchEventUploader` — shared write-side queue.
*:class:`CCRClient` — CCR v2 client wrapper. ( exports a sibling
  ``CCRInitError`` exception class which is not yet present in the
  Python port; tracked in cli-gap-analysis.md §4.7.)
*:class:`WorkerStateUploader` (+:class:`WorkerStateUploaderConfig`)
  — coalescing PUT /worker uploader.
*:func:`get_transport_for_url` — factory selecting the right transport
  by URL scheme + env vars.
*:class:`RemoteIO` — StructuredIO-style bridge over a Transport
  (WS/Hybrid only — see ``remote_io`` docstring for CCR v2 caveat).
*:class:`Transport` — typing.Protocol every transport satisfies (sans
  ``write``).
"""

from __future__ import annotations

from cloudagent_ext.transports.ccr_client import CCRClient
from cloudagent_ext.transports.hybrid_transport import HybridTransport
from cloudagent_ext.transports.remote_io import RemoteIO
from cloudagent_ext.transports.serial_batch_event_uploader import SerialBatchEventUploader
from cloudagent_ext.transports.sse_transport import SSETransport
from cloudagent_ext.transports.transport_utils import Transport, get_transport_for_url
from cloudagent_ext.transports.websocket_transport import WebSocketTransport
from cloudagent_ext.transports.worker_state_uploader import (
    WorkerStateUploader,
    WorkerStateUploaderConfig,
)

__all__ = [
    'CCRClient',
    'HybridTransport',
    'RemoteIO',
    'SerialBatchEventUploader',
    'SSETransport',
    'Transport',
    'WebSocketTransport',
    'WorkerStateUploader',
    'WorkerStateUploaderConfig',
    'get_transport_for_url',
]
