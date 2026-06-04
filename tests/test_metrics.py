# PROMPT: "Generate comprehensive FastAPI test cases for a store intelligence API covering:
# batch ingest idempotency, metrics computation, funnel accuracy, anomaly detection,
# edge cases (empty store, all-staff, zero purchases, re-entry, backroom breach)."
# CHANGES: Aligned with actual SQLite schema, fixed timestamps, added edge cases,
# corrected assertion values, added anomaly threshold and dual-store tests.

import os
import pytest
from fastapi.testclient import TestClient

os.environ["DB_PATH"] = "/tmp/test_store_intelligence.db"

from app.main import app
from app import database

client = TestClient(app)

STORE_ID = "STORE_BLR_002"
STORE_ID_2 = "STORE_BLR_001"


BASE_EVENT = {
    "store_id": STORE_ID,
    "camera_id": "CAM_ENTRY_01",
    "visitor_id": "VIS_test001",
    "event_type": "ENTRY",
    "timestamp": "2026-03-03T14:15:00Z",
    "zone_id": None,
    "dwell_ms": 0,
    "is_staff": False,
    "confidence": 0.95,
    "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
}


def make_event(**overrides):
    import uuid
    ev = {**BASE_EVENT, "event_id": str(uuid.uuid4()), **overrides}
    return ev


@pytest.fixture(autouse=True)
def fresh_db():
    """Wipe and re-initialise DB before every test."""
    if os.path.exists(os.environ["DB_PATH"]):
        os.remove(os.environ["DB_PATH"])
    database.init_db()
    yield
    if os.path.exists(os.environ["DB_PATH"]):
        os.remove(os.environ["DB_PATH"])


#  Health 

def test_health_returns_healthy():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["datastore_reachable"] is True


def test_health_reports_per_store_status():
    import uuid
    ev = make_event(event_id=str(uuid.uuid4()))
    client.post("/events/ingest", json=[ev])
    r = client.get("/health")
    data = r.json()
    assert STORE_ID in data["stores"]
    assert "feed_status" in data["stores"][STORE_ID]


#  Ingest 

def test_ingest_single_event():
    ev = make_event()
    r = client.post("/events/ingest", json=[ev])
    assert r.status_code == 200
    data = r.json()
    assert data["processed"] == 1
    assert data["duplicates_skipped"] == 0
    assert data["malformed_skipped"] == 0


def test_ingest_idempotent():
    """Posting the same event twice must not double-count it."""
    ev = make_event()
    client.post("/events/ingest", json=[ev])
    r = client.post("/events/ingest", json=[ev])
    assert r.status_code == 200
    assert r.json()["duplicates_skipped"] == 1
    assert r.json()["processed"] == 0


def test_ingest_batch_limit():
    import uuid
    events = [make_event(event_id=str(uuid.uuid4()), visitor_id=f"VIS_{i:06d}") for i in range(501)]
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 400


def test_ingest_empty_batch():
    r = client.post("/events/ingest", json=[])
    assert r.status_code == 400


def test_ingest_multiple_visitors():
    import uuid
    events = [make_event(event_id=str(uuid.uuid4()), visitor_id=f"VIS_{i:06d}") for i in range(5)]
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200
    assert r.json()["processed"] == 5


# Staff exclusion 

def test_staff_excluded_from_footfall():
    import uuid
    customer = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_cust01", is_staff=False)
    staff = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_staff1", is_staff=True)
    client.post("/events/ingest", json=[customer, staff])

    r = client.get(f"/stores/{STORE_ID}/metrics")
    assert r.status_code == 200
    assert r.json()["video_analytics"]["footfall_count"] == 1


def test_all_staff_clip_zero_footfall():
    import uuid
    staff_events = [
        make_event(event_id=str(uuid.uuid4()), visitor_id=f"VIS_s{i:04d}", is_staff=True)
        for i in range(3)
    ]
    client.post("/events/ingest", json=staff_events)
    r = client.get(f"/stores/{STORE_ID}/metrics")
    assert r.json()["video_analytics"]["footfall_count"] == 0


# Re-entry 

def test_reentry_counts_visitor_once_in_funnel():
    import uuid
    entry = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_reent1",
                       event_type="ENTRY", timestamp="2026-03-03T14:10:00Z")
    reentry = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_reent1",
                         event_type="REENTRY", timestamp="2026-03-03T14:30:00Z")
    client.post("/events/ingest", json=[entry, reentry])

    r = client.get(f"/stores/{STORE_ID}/funnel")
    assert r.status_code == 200
    assert r.json()["funnel"]["stage_1_entered"] == 1


# Backroom anomaly 

def test_backroom_breach_creates_anomaly():
    import uuid
    entry = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_breach", event_type="ENTRY",
                       timestamp="2026-03-03T14:00:00Z")
    backroom = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_breach",
                          event_type="ZONE_ENTER", zone_id="BACKROOM",
                          timestamp="2026-03-03T14:05:00Z", is_staff=False)
    client.post("/events/ingest", json=[entry, backroom])

    r = client.get(f"/stores/{STORE_ID}/anomalies")
    assert r.status_code == 200
    data = r.json()
    types = [log["anomaly_type"] for log in data["logs"]]
    assert "UNAUTHORIZED_BACKROOM_ACCESS" in types
    assert data["severity_index"] == "CRITICAL"


def test_staff_backroom_does_not_trigger_anomaly():
    """A staff member in the backroom should NOT trigger an alert."""
    import uuid
    entry = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_staff2",
                       event_type="ENTRY", is_staff=True,
                       timestamp="2026-03-03T09:00:00Z")
    backroom = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_staff2",
                          event_type="ZONE_ENTER", zone_id="BACKROOM",
                          is_staff=True, timestamp="2026-03-03T09:05:00Z")
    client.post("/events/ingest", json=[entry, backroom])

    r = client.get(f"/stores/{STORE_ID}/anomalies")
    types = [log["anomaly_type"] for log in r.json()["logs"]]
    assert "UNAUTHORIZED_BACKROOM_ACCESS" not in types


# Empty store 

def test_empty_store_metrics_no_crash():
    r = client.get(f"/stores/{STORE_ID}/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["video_analytics"]["footfall_count"] == 0
    assert data["video_analytics"]["billing_abandonment_percentage"] == 0.0


def test_empty_store_funnel_no_crash():
    r = client.get(f"/stores/{STORE_ID}/funnel")
    assert r.status_code == 200
    assert r.json()["funnel"]["stage_1_entered"] == 0


def test_empty_store_heatmap_no_crash():
    r = client.get(f"/stores/{STORE_ID}/heatmap")
    assert r.status_code == 200
    assert "spatial_matrix" in r.json()


def test_empty_store_anomalies_no_crash():
    r = client.get(f"/stores/{STORE_ID}/anomalies")
    assert r.status_code == 200
    assert r.json()["severity_index"] == "NORMAL"


#  Metrics 

def test_metrics_billing_visitors():
    import uuid
    entry = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_bill01", event_type="ENTRY")
    zone_enter = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_bill01",
                            event_type="ZONE_ENTER", zone_id="BILLING",
                            timestamp="2026-03-03T14:20:00Z")
    client.post("/events/ingest", json=[entry, zone_enter])

    r = client.get(f"/stores/{STORE_ID}/metrics")
    assert r.status_code == 200
    assert r.json()["video_analytics"]["checkout_visitors"] == 1


def test_metrics_dwell_calculation():
    import uuid
    zone_enter = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_dwell1",
                            event_type="ZONE_ENTER", zone_id="BILLING",
                            timestamp="2026-03-03T14:20:00Z")
    zone_exit = make_event(event_id=str(uuid.uuid4()), visitor_id="VIS_dwell1",
                           event_type="ZONE_EXIT", zone_id="BILLING",
                           dwell_ms=60000, timestamp="2026-03-03T14:21:00Z")
    client.post("/events/ingest", json=[zone_enter, zone_exit])

    r = client.get(f"/stores/{STORE_ID}/metrics")
    dwell = r.json()["video_analytics"]["average_checkout_dwell_seconds"]
    assert dwell == 60.0


def test_metrics_queue_depth_average():
    """Average queue depth should reflect ingested queue_depth values."""
    import uuid
    events = []
    for i, qd in enumerate([2, 3, 4]):
        events.append(make_event(
            event_id=str(uuid.uuid4()), visitor_id=f"VIS_q{i:03d}",
            event_type="ZONE_ENTER", zone_id="BILLING",
            timestamp=f"2026-03-03T14:2{i}:00Z",
            metadata={"queue_depth": qd, "sku_zone": None, "session_seq": 1},
        ))
    client.post("/events/ingest", json=events)
    r = client.get(f"/stores/{STORE_ID}/metrics")
    avg_q = r.json()["video_analytics"]["average_queue_depth"]
    assert avg_q == pytest.approx(3.0, abs=0.2)


#  Funnel 

def test_funnel_stages_are_monotonically_decreasing():
    import uuid
    events = []
    for i in range(10):
        events.append(make_event(event_id=str(uuid.uuid4()), visitor_id=f"VIS_f{i:04d}",
                                 event_type="ENTRY"))
    for i in range(6):
        events.append(make_event(event_id=str(uuid.uuid4()), visitor_id=f"VIS_f{i:04d}",
                                 event_type="ZONE_ENTER", zone_id="SKINCARE_ZONE",
                                 dwell_ms=20000, timestamp="2026-03-03T14:20:00Z"))
        events.append(make_event(event_id=str(uuid.uuid4()), visitor_id=f"VIS_f{i:04d}",
                                 event_type="ZONE_EXIT", zone_id="SKINCARE_ZONE",
                                 dwell_ms=20000, timestamp="2026-03-03T14:21:00Z"))
    for i in range(3):
        events.append(make_event(event_id=str(uuid.uuid4()), visitor_id=f"VIS_f{i:04d}",
                                 event_type="ZONE_ENTER", zone_id="BILLING",
                                 timestamp="2026-03-03T14:25:00Z"))
    client.post("/events/ingest", json=events)

    r = client.get(f"/stores/{STORE_ID}/funnel")
    assert r.status_code == 200
    f = r.json()["funnel"]
    assert f["stage_1_entered"] >= f["stage_2_browsed_aisles"]
    assert f["stage_2_browsed_aisles"] >= f["stage_3_reached_checkout"]


#  Heatmap 

def test_heatmap_ingest_and_retrieve():
    payload = {
        "store_id": STORE_ID,
        "bins": [
            {"x_grid": 0, "y_grid": 0, "frequency": 5},
            {"x_grid": 9, "y_grid": 9, "frequency": 3},
        ]
    }
    r = client.post("/events/heatmap", json=payload)
    assert r.status_code == 200

    r = client.get(f"/stores/{STORE_ID}/heatmap")
    assert r.status_code == 200
    data = r.json()
    assert len(data["spatial_matrix"]) == 10
    assert len(data["spatial_matrix"][0]) == 10
    assert data["spatial_matrix"][0][0] == 100   # normalised to 100 (max)
    assert data["data_confidence"] in ("OK", "LOW")


def test_heatmap_accumulates_on_double_ingest():
    """Ingesting the same cell twice should accumulate frequencies."""
    payload = {"store_id": STORE_ID, "bins": [{"x_grid": 3, "y_grid": 3, "frequency": 4}]}
    client.post("/events/heatmap", json=payload)
    client.post("/events/heatmap", json=payload)

    r = client.get(f"/stores/{STORE_ID}/heatmap")
    assert r.json()["raw_matrix"][3][3] == 8


# Dual-store isolation 

def test_store2_metrics_isolated_from_store1():
    """Events for STORE_BLR_002 must not bleed into STORE_BLR_001 metrics."""
    import uuid
    ev = make_event(event_id=str(uuid.uuid4()), store_id=STORE_ID, visitor_id="VIS_s2cust")
    client.post("/events/ingest", json=[ev])

    r = client.get(f"/stores/{STORE_ID_2}/metrics")
    assert r.status_code == 200
    assert r.json()["video_analytics"]["footfall_count"] == 0


def test_both_stores_reachable():
    for sid in (STORE_ID, STORE_ID_2):
        assert client.get(f"/stores/{sid}/metrics").status_code == 200
        assert client.get(f"/stores/{sid}/funnel").status_code == 200
        assert client.get(f"/stores/{sid}/heatmap").status_code == 200
        assert client.get(f"/stores/{sid}/anomalies").status_code == 200


# 404 for unknown store 

def test_unknown_store_returns_404():
    for endpoint in ("/metrics", "/funnel", "/heatmap", "/anomalies"):
        r = client.get(f"/stores/STORE_UNKNOWN{endpoint}")
        assert r.status_code == 404
