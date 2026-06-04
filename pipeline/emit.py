from __future__ import annotations

import os
from typing import Any, Dict, List

import requests

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_INGEST_URL = f"{API_BASE}/events/ingest"
API_HEATMAP_URL = f"{API_BASE}/events/heatmap"
BATCH_SIZE = 100
REQUEST_TIMEOUT = 5.0


class IngestBatchEmitter:
    """
    Buffers events and POSTs them to the ingest API in batches.
    Call flush() at the end to drain any remaining events.
    """

    def __init__(self, batch_size: int = BATCH_SIZE):
        self.batch_size = batch_size
        self._buffer: List[Dict[str, Any]] = []

    def queue_event(self, event: Dict[str, Any]):
        self._buffer.append(event)
        if len(self._buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        if not self._buffer:
            return
        payload = list(self._buffer)
        self._buffer.clear()
        try:
            resp = requests.post(API_INGEST_URL, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[Emitter] Failed to flush {len(payload)} events: {e}")

    def flush_heatmap(self, store_id: str, bins: List[Dict[str, Any]]):
        if not bins:
            return
        try:
            resp = requests.post(
                API_HEATMAP_URL,
                json={"store_id": store_id, "bins": bins},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[Emitter] Failed to flush heatmap: {e}")
