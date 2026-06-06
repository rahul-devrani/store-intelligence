# Store Intelligence System

Real-time retail analytics from CCTV footage — footfall counting, zone dwell analysis, conversion tracking, queue monitoring, and anomaly detection.

Built for Purplle beauty and cosmetics retail stores. Processes multi-camera CCTV streams using computer vision to generate actionable store performance insights via a REST API and live dashboard.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Stores and Camera Setup](#stores-and-camera-setup)
- [Repository Structure](#repository-structure)
- [Quick Start](#quick-start)
- [Running the Video Pipeline](#running-the-video-pipeline)
- [Dashboard](#dashboard)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Event Schema](#event-schema)
- [Conversion Rate Methods](#conversion-rate-methods)
- [Limitations](#limitations)
- [Future Improvements](#future-improvements)

---

## Overview

Retail stores generate massive volumes of CCTV footage daily — most of it unused. Store managers lack visibility into:

How many customers actually entered the store?
Which zones attract the most dwell time?
Where do customers drop off before reaching billing?
Are queues forming at checkout?
Which areas of the store are dead zones?

The Store Intelligence System answers these questions using YOLOv8-based person detection, ByteTrack multi-object tracking, cross-camera Re-ID, and a FastAPI analytics layer — all deployable via Docker.

---

## Features

### Visitor Analytics

Footfall counting via entry tripwire (CAM_3)
Unique visitor estimation
Re-entry detection across cameras
Staff exclusion via uniform and behaviour heuristics

### Zone Analytics

Per-zone dwell time tracking
Zone occupancy analysis
Dead-zone identification
10x10 spatial heatmap grid

### Billing Analytics

Checkout visitor count
Billing zone queue depth monitoring
Checkout dwell time
Abandonment detection

### Store Analytics

Conversion rate with method transparency (temporal_overlap / approximation)
4-stage visitor funnel with drop-off %
Store-level performance metrics

### Monitoring

API health + per-store feed lag
Stale feed detection
Anomaly alerts (CRITICAL / WARN / INFO)
Structured per-request logging with trace_id

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10, FastAPI, SQLite (WAL mode) |
| Computer Vision | YOLOv8n, OpenCV, ByteTrack |
| Re-Identification | Custom heuristic Re-ID engine |
| Dashboard | Streamlit, Matplotlib |
| Deployment | Docker, Docker Compose |
| Testing | PyTest |

---

## Architecture
CCTV clips (CAM_1 .. CAM_5)
|
v
pipeline/detect.py        YOLOv8n + ByteTrack per-frame detection
pipeline/tracker.py       Same-camera track repair + cross-camera Re-ID
|  (HTTP POST batches)
v
POST /events/ingest       FastAPI ingestion endpoint
app/ingestion.py          Deduplication, session management, SQLite write
|
v
SQLite (WAL mode)         raw_events, visitor_sessions, visitors, heatmap_bins
|
v
GET /stores/{id}/metrics   Real-time analytics
GET /stores/{id}/funnel
GET /stores/{id}/heatmap
GET /stores/{id}/anomalies
GET /stores/{id}/layout

---

## Stores and Camera Setup

### STORE_BLR_001 — Purplle Indiranagar, Bengaluru — Full Coverage

| Camera | Type | Coverage |
|---|---|---|
| CAM_1 | Floor | Skincare wall — Farmstay, TFS, Minimalist, Aqualogi, Foxtal, JC brand bays |
| CAM_2 | Floor | Cosmetics/Makeup floor — L'Oreal, Lakme, Maybelline, Swiss Beauty, Makeup Unit island |
| CAM_3 | Entry | Entrance / glass door — fisheye top-down, tripwire active |
| CAM_5 | Billing | Cash Counter + POS desk + Accessories corner |

Tripwire policy: Tripwires are only placed on type=entry cameras (CAM_3). Floor and billing cameras use zone dwell events for engagement analytics, not footfall counting.

### STORE_BLR_002 — Purplle Brigade Road, Bengaluru — Partial Coverage

| Camera | Type | Coverage |
|---|---|---|
| CAM_4 | Backroom | BOH storeroom — validated from actual footage |

FOH zones (Entrance, Cash Counter, Wall Units, Makeup Unit, Gondolas) are calibrated floor-plan reference polygons only. No live camera feeds confirmed for FOH yet. Do not treat Store 2 FOH analytics as live data.

---

## Repository Structure
```text
store-intelligence/
├── app/                          # Core REST API Application Layer
│   ├── __init__.py
│   ├── main.py                   # FastAPI Application Entrypoint & Routers
│   ├── ingestion.py              # Event Processing, De-duplication & Sessions
│   ├── metrics.py                # Core Business Calculations (Footfall, Dwell)
│   ├── funnel.py                 # 4-Stage Funnel State Computations
│   ├── anomalies.py              # Real-Time Anomaly Detection Engine
│   ├── health.py                 # Camera Feed Lag & Hardware Health Monitors
│   └── models.py                 # Strict Pydantic Verification Schemas
├── pipeline/                     # Computer Vision Processing Node
│   ├── __init__.py
│   ├── detect.py                 # YOLOv8n Inference Worker Execution
│   ├── tracker.py                # ByteTrack Integration & Multi-Object Tracking
│   ├── reid.py                   # Cross-Camera Structural Identity Matcher
│   ├── zone_mapper.py            # Geometric Polygon Boundary Engine
│   ├── emit.py                   # Async REST API Transaction Forwarder
│   └── run.sh                    # Automation Script for Video Processing
├── data/                         # Persistent Configuration & Assets
│   ├── store_layout.json         # Master Floor-Plan Polygon Mapping Coordinates
│   ├── pos_transactions.csv      # Local Point-Of-Sale Transaction Log Samples
│   ├── store1.png                # Floor-Plan Layout — Indiranagar Store
│   ├── store2.png                # Floor-Plan Layout — Brigade Road Store
│   └── clips/                    # Target Video Files Storage Root
├── tests/                        # Comprehensive Testing Core
│   ├── __init__.py
│   ├── test_api.py               # Functional Endpoint Test Matrix
│   └── test_pipeline.py          # Vision Algorithm Suite Asserts
├── dashboard.py                  # Streamlit Real-Time Analytical UI Front-End
├── run_pipeline.py               # Top-Level Automation Core Engine
├── Dockerfile                    # Multi-Stage System Docker Build Blueprint
├── docker-compose.yml            # Application Services Orchestration Spec
├── requirements.txt              # Standard Python Library Version Tree
└── README.md                     # Deep System Blueprint Manual

```

## Quick Start

### Prerequisites

Docker and Docker Compose installed
CCTV video footage
YOLOv8n model weights (yolov8n.pt)

Note: CCTV videos (*.mp4), SQLite databases (*.db), and YOLO weights (*.pt) are excluded from this repository due to privacy and size constraints. You must provide your own footage.

### Option 1: Docker (Recommended)

```bash
git clone https://github.com/rahul-devrani/store-intelligence.git
cd store-intelligence

docker compose build
docker compose up
```

API will be available at:

Swagger UI   http://localhost:8000/docs
Health check http://localhost:8000/health

```bash
docker compose down
```

### Option 2: Local (Python)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

## Running the Video Pipeline

The API server and video pipeline are independent components. The API runs without footage. The pipeline generates analytics from CCTV clips.

### Step 1: Place Videos
data/
clips/
STORE_BLR_001/
CAM_1/    floor.mp4
CAM_2/    floor.mp4
CAM_3/    entry.mp4
CAM_5/    billing.mp4
STORE_BLR_002/
CAM_4/    backroom.mp4

### Step 2: Activate Environment and Run

```bash
venv\Scripts\activate

python run_pipeline.py
```

The pipeline automatically:

1. Loads all stores and cameras from store_layout.json
2. Runs YOLOv8n person detection per frame
3. Runs ByteTrack tracking
4. Performs cross-camera visitor Re-ID
5. Maps detections to zone polygons
6. Generates structured analytics events
7. Ingests events into SQLite via the API

Expected output:
PROCESSING STORE: STORE_BLR_001
...
Store session finalized: STORE_BLR_001
PROCESSING STORE: STORE_BLR_002
...
Store session finalized: STORE_BLR_002
ALL STORES PROCESSED SUCCESSFULLY

---

## Dashboard

```bash
pip install streamlit Pillow matplotlib
streamlit run dashboard.py
```

Open http://localhost:8501

Dashboard tabs:

Funnel        4-stage conversion with drop-off %
Heatmap       Spatial density overlaid on floor-plan PNG
Zone Layout   All polygons + tripwires on floor plan
Zone Dwell    Per-zone average dwell bar chart
Anomalies     Active alerts with severity and suggested actions
Diagnostics   Event density, fragmentation, totals

Place store1.png and store2.png in data/ for the floor-plan overlay. Without PNGs the dashboard falls back to an SVG normalised-coordinate viewer.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | /health | Service health + per-store feed lag + stale feed status |
| GET | /stores | List all registered stores and cameras |
| POST | /events/ingest | Batch ingest up to 500 events (idempotent) |
| POST | /events/heatmap | Ingest spatial heatmap coordinates |
| GET | /stores/{id}/metrics | Footfall, conversion, dwell, queue depth |
| GET | /stores/{id}/funnel | 4-stage funnel with drop-off % |
| GET | /stores/{id}/heatmap | 10x10 normalised spatial density grid |
| GET | /stores/{id}/anomalies | Active anomalies with severity |
| GET | /stores/{id}/layout | Zone polygons + tripwires |

### Sample: Health Response

```json
{
  "status": "healthy",
  "datastore_reachable": true,
  "total_events_stored": 1234,
  "store_feed_status": {
    "STORE_BLR_001": {
      "latest_event_timestamp": 1748970123.4,
      "feed_lag_seconds": 42,
      "stale_feed": false
    },
    "STORE_BLR_002": {
      "latest_event_timestamp": null,
      "feed_lag_seconds": null,
      "stale_feed": true
    }
  }
}
```

### Sample: Metrics Request

```bash
curl http://localhost:8000/stores/STORE_BLR_001/metrics
```

---

## Testing

```bash
pytest tests -v

docker compose exec store_intelligence_api pytest tests -v
```

---

## Event Schema

All events are validated via Pydantic before ingestion. Duplicate event IDs are safely ignored.

```json
{
  "event_id": "8d1ab3b8-5d7f-4e7c-a55d-12f20dbbb001",
  "store_id": "STORE_BLR_001",
  "camera_id": "CAM_3",
  "visitor_id": "VIS_001",
  "event_type": "ENTRY",
  "timestamp": "2026-03-03T14:22:10Z",
  "zone_id": "ENTRANCE",
  "dwell_ms": 0,
  "is_staff": false,
  "confidence": 0.92,
  "metadata": {
    "session_seq": 1
  }
}
```

---

## Conversion Rate Methods

Every /metrics response includes a conversion_method field indicating how conversion was computed.

| Method | Description |
|---|---|
| temporal_overlap | Precise. CCTV billing zone visitor matched to a POS transaction within a 5-minute window. Requires timestamp alignment between CCTV and POS. |
| approximation | Approximate. POS order count divided by CCTV footfall count. Used when temporal alignment is unavailable. May over or under count. |
| unavailable | No data — zero footfall or zero POS orders recorded. |

Store 1 currently uses approximation mode. The POS sample file (pos_transactions.csv) uses order_date and order_time fields but does not carry visitor IDs from CCTV.

---

## Limitations

| Area | Known Limitation |
|---|---|
| Re-ID | Heuristic-based; same visitor may receive multiple IDs across sessions or cameras |
| Detection | YOLOv8n is speed-optimised; may miss detections in crowded or occluded scenes |
| Queue Estimation | Based on zone occupancy — not always equal to actual queue length |
| Conversion | POS not directly linked to CCTV visitors; approximation used for now |
| Multi-Camera Tracking | Viewpoint and lighting differences make cross-camera matching imperfect |
| Database | SQLite is suitable for prototyping; not ideal for high-throughput production |

---

## Future Improvements

Deep Re-ID models (OSNet / FastReID)
GPU inference workers
PostgreSQL backend
Redis caching layer
Kafka event streaming
WebSocket real-time dashboard updates
Historical trend analytics
Multi-store horizontal scaling
Learned staff classification model
Automatic camera health monitoring
Cloud deployment support

---

## Challenge Requirement Mapping

| Requirement | Implementation |
|---|---|
| Detection Layer | YOLOv8n + ByteTrack + custom Re-ID |
| Event Stream | Structured JSON schema with batched ingestion |
| Real-Time API | FastAPI analytics service |
| Footfall Counting | Entry tripwire on CAM_3 |
| Re-entry Detection | Cross-camera Re-ID engine |
| Staff Exclusion | Uniform + behaviour heuristic classifier |
| Conversion Tracking | POS correlation layer |
| Funnel Analytics | Session-based visitor funnel |
| Heatmap Analytics | 10x10 spatial aggregation grid |
| Queue Monitoring | Billing zone occupancy tracking |
| Anomaly Detection | Queue spikes, dead zones, stale feeds |
| Production Deployment | Docker Compose |
| Dashboard | Streamlit live analytics UI |

---
