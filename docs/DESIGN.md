# DESIGN.md — Store Intelligence System

# 1. System Overview

The goal of this project is to transform raw anonymized retail CCTV footage into actionable store intelligence. The system processes multi-camera video streams, generates behavioural events, stores them in a real-time analytics backend, and exposes operational metrics through a REST API and live dashboard.

The architecture follows an event-driven pipeline:

```
CCTV Footage
     │
     ▼
Detection + Tracking Layer
     │
     ▼
Structured Event Stream
     │
     ▼
FastAPI Intelligence API
     │
     ▼
SQLite Analytics Store
     │
     ▼
Dashboard + Analytics Consumers
```

The design prioritizes simplicity, explainability, and operational robustness over maximum computer vision accuracy.

---

# 2. Detection Layer

The detection layer is implemented inside the `pipeline/` package.

Components:

* `detect.py`
* `tracker.py`
* `reid.py`
* `zone_mapper.py`
* `emit.py`

YOLOv8n is used for person detection because it provides an effective trade-off between inference speed and accuracy on commodity hardware.

ByteTrack is used for object tracking because it maintains stable track IDs even when detections momentarily degrade.

Video clips are sampled every fifth frame.

At 15 FPS source footage this produces an effective processing rate of approximately 3 FPS while significantly reducing CPU requirements.

For each tracked individual the following operations occur:

1. Person detection
2. Tracking ID assignment
3. Zone containment evaluation
4. Tripwire crossing evaluation
5. Staff classification
6. Re-identification
7. Event emission

The output of the detection layer is a stream of structured behavioural events.

---

# 3. Session Lifecycle

A visitor session begins when an ENTRY event is emitted.

The session progresses through:

ENTRY
→ ZONE_ENTER
→ ZONE_DWELL
→ BILLING_QUEUE_JOIN
→ EXIT

If a visitor exits and later returns, a REENTRY event is generated instead of creating a completely unrelated visitor record.

This prevents conversion inflation and improves funnel accuracy.

Session state is maintained independently from the analytics layer so that event replay remains deterministic.

---

# 4. Event Stream Design

The event stream serves as the contract between computer vision and analytics.

All events conform to a common schema:

* event_id
* store_id
* camera_id
* visitor_id
* event_type
* timestamp
* zone_id
* confidence
* metadata

The schema was intentionally designed to support future event types without changing ingestion logic.

Events are batched before transmission to reduce API overhead.

The ingestion endpoint is idempotent using event_id as the uniqueness key.

This allows safe replay of historical footage and simplifies recovery after failures.

---

# 5. Storage Architecture

SQLite was selected as the persistence layer.

Reasons:

* Zero operational overhead
* Single-file deployment
* Suitable for challenge scale workloads
* Excellent local development experience

WAL mode is enabled.

This allows:

* Concurrent reads
* Concurrent writes
* Dashboard queries during ingestion

Tables:

* raw_events
* visitors
* visitor_sessions
* heatmap_bins

The storage model is intentionally normalized enough for analytics while remaining simple to reason about.

---

# 6. Intelligence API

The API is implemented using FastAPI.

Endpoints:

* POST /events/ingest
* GET /stores/{id}/metrics
* GET /stores/{id}/funnel
* GET /stores/{id}/heatmap
* GET /stores/{id}/anomalies
* GET /health

All analytics are computed directly from event data.

Metrics are not precomputed.

This guarantees consistency between stored events and reported analytics.

The API is designed to gracefully handle:

* Empty stores
* Zero purchases
* All-staff scenarios
* Stale feeds
* Duplicate event submissions

---

# 7. Dashboard

The Streamlit dashboard acts as the operational visualization layer.

It displays:

* Footfall
* Conversion rate
* Revenue
* Funnel progression
* Heatmaps
* Zone dwell
* Active anomalies
* Feed health

The dashboard consumes only API responses and never accesses the database directly.

This ensures the dashboard behaves exactly like any external analytics consumer.

---

# 8. AI-Assisted Decisions

## Staff Classification

AI suggested using a multimodal vision model to classify staff members.

This approach was rejected because it introduces network latency, API cost, and external dependencies.

A lightweight heuristic based on uniform colour detection and zone occupancy behaviour was adopted instead.

---

## Re-Identification Strategy

AI suggested a deep Re-ID architecture using OSNet.

While accurate, the approach significantly increased deployment complexity.

For challenge constraints a histogram-based appearance descriptor with cosine similarity provided an acceptable trade-off between performance and simplicity.

---

## Session Design

AI suggested using visitor_id plus calendar date as the session key.

This approach incorrectly merges multiple visits from the same customer on the same day.

The final implementation uses session state transitions and explicit REENTRY events to preserve visit boundaries.

---

# 9. Future Improvements

Potential production upgrades include:

* Deep Re-ID models (OSNet)
* Kafka event streaming
* PostgreSQL analytics backend
* Redis caching
* GPU inference pipeline
* Multi-store distributed deployment
* Learned staff classification models

These enhancements were intentionally excluded to keep the solution deployable through a single docker compose command while satisfying challenge requirements.
