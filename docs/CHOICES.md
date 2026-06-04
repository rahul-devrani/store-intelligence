# CHOICES.md — Key Engineering Decisions

## Decision 1 — Detection Model: YOLOv8n + ByteTrack

**Options considered:**
- YOLOv8n (nano) — fastest, ~6ms/frame on CPU
- YOLOv8s (small) — 2× slower, better accuracy on partial occlusions
- RT-DETR — transformer-based, strong accuracy but 4× inference cost
- MediaPipe Pose — good for single person, degrades with crowds

**What AI suggested:** Claude suggested YOLOv8s as a better trade-off for the
billing clip partial occlusion cases, noting that nano struggles when people are
>50% occluded by shelving.

**What I chose and why:** YOLOv8n for this submission with `confidence=0.45`
threshold. The key insight is that ByteTrack's Kalman filter recovers tracks through
short occlusions (2-3 frames) without requiring the detector to fire. At the 5-frame
skip rate used here, occlusion is mostly invisible to the tracker. If running on
GPU in production, YOLOv8s is a drop-in upgrade (same API call).

**Partial occlusion handling:** The `LocalTrackRepairer` stitches tracks that
disappear for ≤2 seconds with matching position + bounding box size — this covers
people stepping behind a display and re-emerging.

---

## Decision 2 — Event Schema Design

**Core question:** Should a visitor's ID be stable across cameras?

**Options considered:**
1. Per-camera visitor IDs, deduplicate at query time
2. Global visitor IDs assigned at entry, inherited by Re-ID
3. Probabilistic IDs that merge post-hoc

**What AI suggested:** Option 3 with a post-hoc merge step using a Union-Find
structure keyed on (camera_id, entry_timestamp, descriptor_similarity).

**What I chose and why:** Option 2. The Re-ID engine assigns the same visitor_id
when it detects the same person entering a new camera's FOV. This means the API
layer never needs to deduplicate — `COUNT(DISTINCT visitor_id)` is always correct.
The tradeoff is a false negative Re-ID (missed same-person match) creates a harmless
slight overcount, whereas a false positive (two people merged) causes undercounting —
which is the more misleading error. Threshold set conservatively at 0.82 cosine
similarity for this reason.

**Schema compliance:** All events include `event_id` (UUID v4), `timestamp`
(ISO-8601 UTC), `confidence` (never suppressed), `session_seq` (monotonic counter
per visitor), and `metadata.queue_depth` (null for non-billing events).

---

## Decision 3 — API Storage: SQLite in WAL Mode

**Options considered:**
- SQLite (WAL mode) — zero infra, file-based, concurrent reads
- PostgreSQL — production-grade, needs a separate container + connection pool
- DuckDB — excellent analytical queries, less battle-tested for write-heavy workloads

**What AI suggested:** PostgreSQL for production readiness, noting SQLite has
write serialisation that would bottleneck a high-ingest pipeline.

**What I chose and why:** SQLite in WAL mode. The challenge runs a single store
pipeline feeding a single API instance — SQLite WAL handles this without contention.
WAL mode specifically allows concurrent readers during writes, which matters here
(pipeline writing, dashboard reading simultaneously). The DB_PATH is injected via
environment variable, making it trivial to swap to PostgreSQL by changing the
connection string in `database.py`. DuckDB was tempting for the analytical queries
but its write path is less suited to the event-stream pattern.

**Indices added:** `(store_id, timestamp)`, `(store_id, visitor_id)` on `raw_events`
to keep the metric queries sub-10ms even with 100k+ events.
