# DESIGN.md — Store Intelligence System

## Architecture Overview

The system is a three-stage pipeline: **Detection → Event Stream → Intelligence API**.

```
CCTV clips
    │
    ▼
pipeline/detect.py        YOLOv8n + ByteTrack per-frame detection
pipeline/tracker.py       Same-camera track repair + cross-camera Re-ID
    │  (HTTP POST batches)
    ▼
POST /events/ingest       FastAPI ingestion endpoint
app/ingestion.py          Deduplication, session management, SQLite write
    │
    ▼
SQLite (WAL mode)         raw_events, visitor_sessions, visitors, heatmap_bins
    │
    ▼
GET /stores/{id}/metrics  Real-time analytics queries
GET /stores/{id}/funnel
GET /stores/{id}/heatmap
GET /stores/{id}/anomalies
```

### Detection Layer
`StoreStreamEngine` in `pipeline/detect.py` opens each clip and runs YOLOv8n with
ByteTrack (`model.track(..., persist=True, tracker="bytetrack.yaml")`). Every 5th
frame is processed to reduce CPU load without meaningfully impacting accuracy at
15 fps source video (effective: 3 fps sampled).

**Per-detection pipeline for each tracked person:**
1. Zone polygon containment test (Shapely Point-in-Polygon)
2. Tripwire direction check (dot product of movement vs. direction vector)
3. Same-camera track repair (`LocalTrackRepairer`) — recovers IDs lost during occlusion
4. Cross-camera Re-ID (`CrossCameraReIDEngine`) — cosine similarity on 16-bin grayscale histogram
5. Staff classification — black-uniform ratio (HSV mask on upper torso) + zone dwell ratio + track lifetime ratio
6. Session state machine — emits ENTRY, ZONE_ENTER, ZONE_DWELL, ZONE_EXIT, EXIT, REENTRY, BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON

### Event Stream
Events are batched in `IngestBatchEmitter` (100 events/batch) and POSTed to the API.
This decouples the CV pipeline from the API — the pipeline can run offline and replay
events later.

### Intelligence API
FastAPI + SQLite (WAL mode). All metric queries are real-time SQL aggregations — no
caching layer. WAL mode allows concurrent reads during writes (pipeline ingesting
while API responds to queries).

### Storage Schema
- `raw_events` — every event emitted by the pipeline, deduplicated by `event_id`
- `visitors` — one row per (visitor_id, store_id), tracks staff flag
- `visitor_sessions` — session lifecycle with start/end timestamps
- `heatmap_bins` — 10×10 grid frequency accumulator

---

## AI-Assisted Decisions

### 1. Staff classification approach
Initial AI suggestion: use a VLM (GPT-4V / Gemini) to classify staff in each frame
by sending cropped images to the vision API. **Override**: this would add ~300ms
latency per detection and significant API cost at 3fps × multiple cameras. Instead
adopted a two-signal heuristic: (a) black-uniform HSV mask on the upper 30% of the
bounding box, and (b) zone dwell ratio — staff spend >70% of time in BILLING or
BACKROOM. This runs in <1ms per detection and is robust for uniform-based retail
staff.

### 2. Re-ID descriptor choice
AI suggested using a deep Re-ID model (OSNet/torchreid) for cross-camera matching.
**Agreed partially**: a full Re-ID model gives better accuracy but adds a 300MB model
weight and ~20ms/inference overhead. For this challenge's 15s cross-camera handover
window and a small descriptor space (one store, 3 cameras), a 16-bin grayscale
histogram with cosine similarity threshold 0.82 is sufficient. Added as a future
upgrade path in the code.

### 3. Session deduplication key
AI suggested using `visitor_id + date` as the session key. **Override**: used
`visitor_id + timestamp_seconds` to allow multiple same-day sessions (customers who
leave and return). The REENTRY event type handles the re-entry case explicitly.
