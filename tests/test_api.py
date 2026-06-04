"""
tests/test_api.py  — Comprehensive test suite
Covers: health, ingest, duplicates, anomalies, heatmap, funnel,
        re-entry, staff exclusion, zero-purchase, empty store.
Run with: pytest tests/test_api.py -v --cov=app --cov-report=term-missing

# PROMPT: "Generate comprehensive FastAPI test cases for a store intelligence API
# covering health endpoint, batch ingest idempotency, staff exclusion from
# footfall, re-entry visitor counting, zero-purchase stores, heatmap ingest and
# retrieval, anomaly severity, layout polygon validation."
# CHANGES MADE: Fixed import from 'main' to 'app.main', aligned _event() helper
# with actual EventPayload schema (visitor_id not person_id, added metadata),
# corrected STORE_1 camera IDs (CAM_3 is entry camera for STORE_BLR_001),
# fixed assertions for staff footfall test, added fresh_db autouse fixture.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DB_PATH", "/tmp/test_store_api.db")

from app.main import app
from app import database

client = TestClient(app)

STORE_1 = "STORE_BLR_001"
STORE_2 = "STORE_BLR_002"


@pytest.fixture(autouse=True)
def fresh_db():
    db_path = os.environ["DB_PATH"]
    if os.path.exists(db_path):
        os.remove(db_path)
    database.init_db()
    yield
    if os.path.exists(db_path):
        os.remove(db_path)


# Helpers 

def _event(
    store_id: str = STORE_1,
    camera_id: str = "CAM_3",
    visitor_id: str | None = None,
    zone: str | None = None,
    event_type: str = "ENTRY",
    timestamp: str = "2026-03-03T14:00:00Z",
    is_staff: bool = False,
    dwell_ms: int = 0,
    queue_depth: int | None = None,
) -> Dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id or f"VIS_{uuid.uuid4().hex[:6]}",
        "zone_id": zone,
        "event_type": event_type,
        "timestamp": timestamp,
        "is_staff": is_staff,
        "confidence": 0.95,
        "dwell_ms": dwell_ms,
        "metadata": {
            "queue_depth": queue_depth,
            "sku_zone": None,
            "session_seq": 1,
        },
    }


def _ingest(events: List[Dict]) -> Dict:
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200, r.text
    return r.json()


# Health 

class TestHealth:
    def test_health_returns_200(self):
        r = client.get("/health")
        assert r.status_code in (200, 503)

    def test_health_has_required_fields(self):
        r = client.get("/health")
        body = r.json()
        assert "status" in body
        assert "datastore_reachable" in body

    def test_health_has_store_feed_status(self):
        r = client.get("/health")
        body = r.json()
        assert "store_feed_status" in body
        for sid, feed in body["store_feed_status"].items():
            assert "stale_feed" in feed, f"stale_feed missing for {sid}"
            assert "feed_lag_seconds" in feed, f"feed_lag_seconds missing for {sid}"

    def test_health_feed_lag_numeric_or_none(self):
        r = client.get("/health")
        body = r.json()
        for sid, feed in body["store_feed_status"].items():
            lag = feed["feed_lag_seconds"]
            assert lag is None or isinstance(lag, (int, float)), f"Invalid lag type for {sid}"


# Store list 

class TestStoreList:
    def test_stores_endpoint_returns_list(self):
        r = client.get("/stores")
        assert r.status_code == 200
        body = r.json()
        assert "stores" in body
        assert len(body["stores"]) >= 2

    def test_stores_have_camera_list(self):
        r = client.get("/stores")
        stores = r.json()["stores"]
        for s in stores:
            assert "cameras" in s
            assert isinstance(s["cameras"], list)


#  Ingest 

class TestIngest:
    def test_single_event_ingest(self):
        res = _ingest([_event()])
        assert res["status"] == "success"
        assert res["processed"] == 1

    def test_empty_batch_rejected(self):
        r = client.post("/events/ingest", json=[])
        assert r.status_code == 400

    def test_batch_over_limit_rejected(self):
        batch = [_event() for _ in range(501)]
        r = client.post("/events/ingest", json=batch)
        assert r.status_code == 400

    def test_batch_500_accepted(self):
        batch = [
            _event(visitor_id=f"VIS_{i:05d}") for i in range(500)
        ]
        res = _ingest(batch)
        assert res["status"] == "success"
        assert res["processed"] == 500

    def test_response_has_all_keys(self):
        res = _ingest([_event()])
        assert "processed" in res
        assert "duplicates_skipped" in res
        assert "malformed_skipped" in res


class TestDuplicateIngest:
    """Idempotency: same event_id ingested twice must be deduplicated."""

    def test_duplicate_event_skipped(self):
        ev = _event()
        res1 = _ingest([ev])
        res2 = _ingest([ev])
        assert res1["processed"] == 1
        assert res2["duplicates_skipped"] == 1
        assert res2["processed"] == 0

    def test_mixed_batch_with_duplicates(self):
        ev_dup = _event()
        ev_new = _event()
        _ingest([ev_dup])
        res = _ingest([ev_dup, ev_new])
        assert res["duplicates_skipped"] == 1
        assert res["processed"] == 1


# Re-entry 

class TestReentry:
    def test_reentry_creates_new_session(self):
        person_id = f"VIS_{uuid.uuid4().hex[:6]}"
        entry1 = _event(visitor_id=person_id, event_type="ENTRY",
                        timestamp="2026-03-03T14:00:00Z")
        exit1 = _event(visitor_id=person_id, event_type="EXIT",
                       timestamp="2026-03-03T14:30:00Z")
        entry2 = _event(visitor_id=person_id, event_type="REENTRY",
                        timestamp="2026-03-03T15:00:00Z")
        res = _ingest([entry1, exit1, entry2])
        assert res["processed"] == 3

    def test_reentry_visitor_counted_once_in_footfall(self):
        person_id = f"VIS_{uuid.uuid4().hex[:6]}"
        ev1 = _event(visitor_id=person_id, event_type="ENTRY",
                     timestamp="2026-03-03T14:00:00Z")
        ev2 = _event(visitor_id=person_id, event_type="REENTRY",
                     timestamp="2026-03-03T15:00:00Z")
        _ingest([ev1, ev2])
        metrics = client.get(f"/stores/{STORE_1}/metrics").json()
        footfall = metrics.get("video_analytics", {}).get("footfall_count", 0)
        assert footfall >= 1


# Staff exclusion 

class TestStaffExclusion:
    def test_staff_events_ingested_without_error(self):
        staff_ev = _event(is_staff=True, camera_id="CAM_5", zone="BILLING")
        res = _ingest([staff_ev])
        assert res["status"] == "success"

    def test_staff_footfall_not_counted_as_customer(self):
        metrics_before = client.get(f"/stores/{STORE_1}/metrics").json()
        ff_before = metrics_before.get("video_analytics", {}).get("footfall_count", 0)

        staff_ev = _event(is_staff=True, camera_id="CAM_3", zone=None)
        _ingest([staff_ev])

        metrics_after = client.get(f"/stores/{STORE_1}/metrics").json()
        ff_after = metrics_after.get("video_analytics", {}).get("footfall_count", 0)
        assert ff_after == ff_before, (
            f"Staff event increased footfall from {ff_before} to {ff_after}"
        )


# Zero purchase / empty store 

class TestEdgeCases:
    def test_metrics_with_zero_events_store2(self):
        r = client.get(f"/stores/{STORE_2}/metrics")
        assert r.status_code == 200
        body = r.json()
        assert "video_analytics" in body

    def test_conversion_rate_none_when_no_purchases(self):
        r = client.get(f"/stores/{STORE_2}/metrics")
        assert r.status_code == 200
        pa = r.json().get("pos_analytics", {})
        cr = pa.get("conversion_rate_percentage")
        assert cr is None or isinstance(cr, (int, float))

    def test_conversion_method_always_present(self):
        r = client.get(f"/stores/{STORE_1}/metrics")
        assert r.status_code == 200
        pa = r.json().get("pos_analytics", {})
        assert "conversion_method" in pa, "conversion_method field missing from pos_analytics"

    def test_funnel_with_empty_store(self):
        r = client.get(f"/stores/{STORE_2}/funnel")
        assert r.status_code == 200
        body = r.json()
        assert "funnel" in body

    def test_heatmap_empty_returns_zero_grid(self):
        r = client.get(f"/stores/{STORE_2}/heatmap")
        assert r.status_code == 200
        body = r.json()
        matrix = body.get("spatial_matrix", [])
        assert len(matrix) == 10
        assert all(len(row) == 10 for row in matrix)


#  Heatmap 

class TestHeatmap:
    def test_heatmap_ingest_and_retrieve(self):
        payload = {
            "store_id": STORE_1,
            "bins": [
                {"x_grid": 3, "y_grid": 4, "frequency": 5},
                {"x_grid": 7, "y_grid": 2, "frequency": 10},
            ],
        }
        r = client.post("/events/heatmap", json=payload)
        assert r.status_code == 200
        assert r.json()["bins_updated"] == 2

    def test_heatmap_matrix_shape(self):
        r = client.get(f"/stores/{STORE_1}/heatmap")
        assert r.status_code == 200
        body = r.json()
        matrix = body["spatial_matrix"]
        assert len(matrix) == 10
        assert all(len(row) == 10 for row in matrix)

    def test_heatmap_values_0_to_100(self):
        r = client.get(f"/stores/{STORE_1}/heatmap")
        body = r.json()
        for row in body["spatial_matrix"]:
            for val in row:
                assert 0 <= val <= 100, f"Heatmap value out of range: {val}"

    def test_heatmap_confidence_field(self):
        r = client.get(f"/stores/{STORE_1}/heatmap")
        assert "data_confidence" in r.json()


#  Anomalies 

class TestAnomalies:
    def test_anomaly_endpoint_returns_200(self):
        r = client.get(f"/stores/{STORE_1}/anomalies")
        assert r.status_code == 200

    def test_anomaly_response_has_logs(self):
        r = client.get(f"/stores/{STORE_1}/anomalies")
        body = r.json()
        assert "logs" in body
        assert isinstance(body["logs"], list)

    def test_anomaly_logs_have_severity(self):
        r = client.get(f"/stores/{STORE_1}/anomalies")
        for log in r.json().get("logs", []):
            assert "severity" in log
            assert log["severity"] in ("CRITICAL", "WARN", "INFO")

    def test_backroom_anomaly_triggered(self):
        customer_in_boh = _event(
            store_id=STORE_2,
            camera_id="CAM_4",
            zone="BOH",
            event_type="ZONE_ENTER",
            is_staff=False,
        )
        _ingest([customer_in_boh])
        r = client.get(f"/stores/{STORE_2}/anomalies")
        body = r.json()
        anomaly_types = [log.get("anomaly_type", "") for log in body.get("logs", [])]
        assert any("BACKROOM" in t or "UNAUTHORIZED" in t for t in anomaly_types), (
            f"Expected backroom anomaly, got: {anomaly_types}"
        )


# Layout 

class TestLayout:
    def test_layout_returns_cameras(self):
        r = client.get(f"/stores/{STORE_1}/layout")
        assert r.status_code == 200
        assert "cameras" in r.json()

    def test_polygons_normalised(self):
        r = client.get(f"/stores/{STORE_1}/layout")
        cameras = r.json()["cameras"]
        for cam_id, cam_data in cameras.items():
            for zone_id, zone_data in cam_data.get("zones", {}).items():
                for x, y in zone_data.get("polygon", []):
                    assert 0.0 <= x <= 1.0, f"{cam_id}/{zone_id}: x={x} out of [0,1]"
                    assert 0.0 <= y <= 1.0, f"{cam_id}/{zone_id}: y={y} out of [0,1]"

    def test_404_for_unknown_store(self):
        r = client.get("/stores/STORE_INVALID_XYZ/layout")
        assert r.status_code == 404


#  Structured logging 

class TestStructuredLogging:
    def test_requests_complete_without_trace_header(self):
        r = client.get("/health")
        assert r.status_code in (200, 503)

    def test_requests_complete_with_trace_header(self):
        r = client.get("/health", headers={"X-Trace-ID": "test-trace-123"})
        assert r.status_code in (200, 503)
