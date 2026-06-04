# Challenge Requirement Mapping

| Challenge Requirement | Implementation                                      |
| --------------------- | --------------------------------------------------- |
| Detection Layer       | YOLOv8n + ByteTrack + custom Re-ID                  |
| Event Stream          | Structured JSON event schema with batched ingestion |
| Real-Time API         | FastAPI analytics service                           |
| Footfall Counting     | Entry tripwire detection                            |
| Re-entry Detection    | Cross-camera Re-ID engine                           |
| Staff Exclusion       | Uniform + behaviour heuristic classifier            |
| Conversion Tracking   | POS correlation layer                               |
| Funnel Analytics      | Session-based visitor funnel                        |
| Heatmap Analytics     | 10×10 spatial aggregation grid                      |
| Queue Monitoring      | Billing zone occupancy tracking                     |
| Anomaly Detection     | Queue spikes, dead zones, stale feeds               |
| Production Deployment | Docker Compose                                      |
| Dashboard             | Streamlit live analytics UI                         |

---

# Event Schema Example

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

All events are validated before ingestion using Pydantic models.

Duplicate event IDs are safely ignored.

---

# Logging

Every API request generates structured logs containing:

* trace_id
* endpoint
* store_id
* latency_ms
* status_code
* event_count (ingestion only)

Example:

```json
{
  "trace_id": "req_81aa92",
  "endpoint": "/events/ingest",
  "store_id": "STORE_BLR_001",
  "event_count": 100,
  "latency_ms": 34,
  "status_code": 200
}
```

---

# Known Limitations

1. Store 2 currently contains validated footage only for CAM_4 (Back Of House).

2. Staff detection is heuristic-based and may require retraining for stores using different uniforms.

3. Histogram-based Re-ID is intentionally lightweight and may be less accurate than deep Re-ID models under severe appearance changes.

4. Conversion tracking currently falls back to approximation mode when CCTV and POS timestamps are not aligned.

5. SQLite is sufficient for challenge-scale workloads but should be replaced by PostgreSQL for large multi-store deployments.

---

# Future Improvements

Potential production upgrades:

* Deep Re-ID using OSNet
* Kafka event streaming
* PostgreSQL backend
* Redis caching layer
* GPU inference workers
* Multi-store horizontal scaling
* Learned staff classification model
* Real-time WebSocket dashboard updates
* Automatic camera health monitoring
* Historical trend analytics

---

# Repository Structure

```text
store-intelligence/
│
├── app/
│   ├── main.py
│   ├── ingestion.py
│   ├── metrics.py
│   ├── funnel.py
│   ├── anomalies.py
│   ├── health.py
│   └── models.py
│
├── pipeline/
│   ├── detect.py
│   ├── tracker.py
│   ├── reid.py
│   ├── zone_mapper.py
│   ├── emit.py
│   └── run.sh
│
├── data/
│   ├── store_layout.json
│   ├── pos_transactions.csv
│   └── clips/
│
├── tests/
│
├── dashboard.py
├── docker-compose.yml
├── Dockerfile
├── README.md
└── requirements.txt
```
