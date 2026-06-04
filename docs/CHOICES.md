# CHOICES.md — Engineering Trade-offs and Decision Log

This document records the major engineering decisions made while building the Store Intelligence platform. For each decision I describe the alternatives considered, AI-assisted recommendations, the final choice, and the reasoning behind it.

---

# Decision 1 — Detection Model Selection

## Problem

The system must detect people reliably from retail CCTV footage while remaining lightweight enough to run on commodity hardware.

The footage contains:

* Group entries
* Partial occlusions
* Crowded billing queues
* Staff movement
* Empty-store periods
* Multiple camera viewpoints

The detector therefore needs both acceptable accuracy and practical inference speed.

---

## Options Considered

### Option A — YOLOv8n

Advantages:

* Extremely fast
* Small model size
* Easy deployment
* CPU friendly

Disadvantages:

* Slightly weaker on heavy occlusion cases
* Lower recall compared to larger models

---

### Option B — YOLOv8s

Advantages:

* Better recall
* Stronger performance in crowded scenes

Disadvantages:

* Roughly 2× slower
* Higher memory consumption

---

### Option C — RT-DETR

Advantages:

* Strong detection accuracy
* Better transformer-based feature extraction

Disadvantages:

* Significantly slower
* Less suitable for lightweight deployment

---

### Option D — MediaPipe-based approach

Advantages:

* Good for individual people

Disadvantages:

* Struggles with retail crowd scenarios
* Not designed for dense multi-person tracking

---

## What AI Suggested

Claude recommended YOLOv8s because billing-area footage contains several partial occlusion cases where people become temporarily hidden behind displays or other customers.

The recommendation prioritised detection accuracy over inference speed.

---

## Final Choice

### YOLOv8n + ByteTrack

I selected YOLOv8n as the primary detector.

The reason is that the challenge evaluates the full analytics pipeline rather than detector benchmark scores.

Once a person is detected and assigned a track, ByteTrack is capable of maintaining that track through short-term occlusions without requiring the detector to fire every frame.

The detector therefore acts mainly as a track initializer rather than the sole source of identity continuity.

---

## Additional Reliability Layer

A custom LocalTrackRepairer was added.

If a track disappears for ≤2 seconds and later reappears near the previous location with a similar bounding-box size, the track is repaired rather than creating a new visitor.

This reduces:

* False EXIT events
* Duplicate ENTRY events
* Re-identification failures

---

## Future Upgrade Path

For production deployment:

* GPU available → YOLOv8s
* Multi-store deployment → YOLOv8m
* High-density stores → RT-DETR evaluation

The architecture intentionally isolates the detector so model replacement requires minimal code changes.

---

# Decision 2 — Event Schema Design

## Problem

All analytics depend on the event stream.

The schema must support:

* Footfall counting
* Visitor sessions
* Conversion funnels
* Queue monitoring
* Heatmaps
* Re-entry detection
* Anomaly detection

while remaining easy to ingest and validate.

---

## Options Considered

### Option A — Camera-local visitor IDs

Each camera generates independent visitor identifiers.

Advantages:

* Simple implementation

Disadvantages:

* Expensive query-time deduplication
* Incorrect funnel counts

---

### Option B — Global visitor IDs

A visitor retains the same identifier across cameras.

Advantages:

* Simpler analytics
* Correct session aggregation

Disadvantages:

* Requires cross-camera matching

---

### Option C — Probabilistic post-processing merge

Merge visitor identities after ingestion.

Advantages:

* Flexible

Disadvantages:

* Higher complexity
* Harder debugging
* Delayed analytics

---

## What AI Suggested

The AI recommendation was a Union-Find style post-processing merge system where visitors would be merged after ingestion based on similarity scores and timestamps.

This approach reduces detector-side complexity but increases API complexity.

---

## Final Choice

### Global Visitor IDs

The Re-ID engine attempts to assign a single visitor_id across cameras.

This allows:

```text
COUNT(DISTINCT visitor_id)
```

to remain valid throughout the analytics layer.

The API never needs additional deduplication logic.

---

## Why This Matters

The entire challenge revolves around conversion rate:

```text
Converted Visitors / Total Visitors
```

If the same person receives multiple IDs, conversion metrics become inflated.

A conservative matching threshold was therefore preferred.

False negatives slightly overcount visitors.

False positives incorrectly merge different people.

The second error is more harmful.

---

## Event Design Principles

Every event includes:

* event_id (UUIDv4)
* store_id
* camera_id
* visitor_id
* event_type
* timestamp
* confidence
* is_staff
* session_seq

Confidence values are never suppressed.

Low-confidence events are retained and exposed to downstream systems.

This follows the principle that uncertainty should be represented, not hidden.

---

# Decision 3 — Storage Engine and API Architecture

## Problem

The analytics API must support:

* Continuous event ingestion
* Concurrent dashboard reads
* Simple deployment
* Docker-based execution
* Challenge-scale workloads

---

## Options Considered

### Option A — SQLite

Advantages:

* Zero infrastructure
* Simple deployment
* Reliable

Disadvantages:

* Single-writer limitation

---

### Option B — PostgreSQL

Advantages:

* Production-grade
* Better write scalability

Disadvantages:

* Additional operational complexity

---

### Option C — DuckDB

Advantages:

* Excellent analytical queries

Disadvantages:

* Less suited for continuous event ingestion

---

## What AI Suggested

AI recommended PostgreSQL because production retail deployments often involve many stores simultaneously writing events.

This is the correct recommendation for large-scale systems.

---

## Final Choice

### SQLite in WAL Mode

For challenge constraints, SQLite WAL provides the best trade-off.

Benefits:

* No external database container
* Easy local development
* Concurrent reads during writes
* Minimal setup

The pipeline can ingest events while dashboards and API queries execute simultaneously.

---

## Performance Optimisations

Indexes added:

```sql
(store_id, timestamp)

(store_id, visitor_id)

(event_id)
```

These keep analytics queries responsive even as event volume grows.

---

## Production Migration Strategy

The database layer is isolated behind a small access layer.

Future migration path:

```text
SQLite
   ↓
PostgreSQL
   ↓
Kafka + PostgreSQL
   ↓
Kafka + ClickHouse
```

without changing endpoint contracts.

---

# Summary

The guiding principle throughout the project was:

> Prefer simple, explainable, production-aware solutions over unnecessarily complex architectures.

AI was used extensively for evaluating alternatives and identifying trade-offs, but final decisions were made based on deployment simplicity, challenge requirements, observability, and maintainability.
