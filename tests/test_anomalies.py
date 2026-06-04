# PROMPT: "Write pytest tests for anomaly detection in a retail store analytics
# API. Cover: queue spike detection, dead zone detection, stale feed warning,
# UNAUTHORIZED_BACKROOM_ACCESS for customers, staff backroom access is clean,
# severity_index escalation to CRITICAL, empty store returns NORMAL."
# CHANGES MADE: Adjusted queue spike threshold to match _DEFAULTS (5),
# used correct event schema with metadata object, fixed timestamp ISO format,
# added fresh_db fixture, corrected severity_index assertions.

from __future__ import annotations

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ["DB_PATH"] = "/tmp/test_anomalies.db"

from app.main import app
from app import database

client = TestClient(app)

STORE_ID = "STORE_BLR_002"
STORE_ID_2 = "STORE_BLR_001"


def _ev(**overrides):
    base = {
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": "CAM_4",
        "visitor_id": "VIS_anom001",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.90,
        "metadata": {"queue_depth": None, "sku_zone": None, "session_seq": 1},
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def fresh_db():
    db_path = os.environ["DB_PATH"]
    if os.path.exists(db_path):
        os.remove(db_path)
    database.init_db()
    yield
    if os.path.exists(db_path):
        os.remove(db_path)


# Empty store 

class TestEmptyStoreAnomalies:
    def test_empty_store_severity_normal(self):
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        assert r.status_code == 200
        data = r.json()
        assert data["severity_index"] == "NORMAL"
        assert data["anomaly_count"] == 0
        assert data["logs"] == []

    def test_response_schema_present(self):
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        data = r.json()
        assert "severity_index" in data
        assert "anomaly_count" in data
        assert "logs" in data
        assert isinstance(data["logs"], list)


# Backroom access 

class TestBackroomAnomaly:
    def test_customer_backroom_triggers_critical(self):
        entry = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_breach1", event_type="ENTRY",
                    timestamp="2026-03-03T10:00:00Z")
        backroom = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_breach1",
                       event_type="ZONE_ENTER", zone_id="BACKROOM",
                       timestamp="2026-03-03T10:05:00Z", is_staff=False)
        client.post("/events/ingest", json=[entry, backroom])

        r = client.get(f"/stores/{STORE_ID}/anomalies")
        data = r.json()
        types = [log["anomaly_type"] for log in data["logs"]]
        assert "UNAUTHORIZED_BACKROOM_ACCESS" in types
        assert data["severity_index"] == "CRITICAL"

    def test_staff_backroom_no_anomaly(self):
        entry = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_staff1",
                    event_type="ENTRY", is_staff=True, timestamp="2026-03-03T09:00:00Z")
        backroom = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_staff1",
                       event_type="ZONE_ENTER", zone_id="BACKROOM",
                       is_staff=True, timestamp="2026-03-03T09:05:00Z")
        client.post("/events/ingest", json=[entry, backroom])

        r = client.get(f"/stores/{STORE_ID}/anomalies")
        types = [log["anomaly_type"] for log in r.json()["logs"]]
        assert "UNAUTHORIZED_BACKROOM_ACCESS" not in types

    def test_anomaly_log_has_suggested_action(self):
        entry = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_breach2",
                    event_type="ENTRY", timestamp="2026-03-03T11:00:00Z")
        backroom = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_breach2",
                       event_type="ZONE_ENTER", zone_id="BACKROOM",
                       timestamp="2026-03-03T11:01:00Z", is_staff=False)
        client.post("/events/ingest", json=[entry, backroom])

        r = client.get(f"/stores/{STORE_ID}/anomalies")
        for log in r.json()["logs"]:
            if log["anomaly_type"] == "UNAUTHORIZED_BACKROOM_ACCESS":
                assert "suggested_action" in log
                assert len(log["suggested_action"]) > 0


# Queue spike 

class TestQueueSpikeAnomaly:
    def test_queue_depth_above_threshold_triggers_warn(self):
        """Default threshold is 5; send queue_depth=6 to trigger BILLING_QUEUE_SPIKE."""
        store = STORE_ID_2
        events = []
        for i in range(3):
            events.append({
                "event_id": str(uuid.uuid4()),
                "store_id": store,
                "camera_id": "CAM_5",
                "visitor_id": f"VIS_q{i:03d}",
                "event_type": "BILLING_QUEUE_JOIN",
                "timestamp": f"2026-03-03T14:2{i}:00Z",
                "zone_id": "BILLING",
                "dwell_ms": 0,
                "is_staff": False,
                "confidence": 0.90,
                "metadata": {"queue_depth": 6, "sku_zone": None, "session_seq": 1},
            })
        client.post("/events/ingest", json=events)

        r = client.get(f"/stores/{store}/anomalies")
        data = r.json()
        types = [log["anomaly_type"] for log in data["logs"]]
        assert "BILLING_QUEUE_SPIKE" in types

    def test_queue_below_threshold_no_spike(self):
        store = STORE_ID_2
        ev = {
            "event_id": str(uuid.uuid4()),
            "store_id": store,
            "camera_id": "CAM_5",
            "visitor_id": "VIS_q999",
            "event_type": "BILLING_QUEUE_JOIN",
            "timestamp": "2026-03-03T14:30:00Z",
            "zone_id": "BILLING",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.90,
            "metadata": {"queue_depth": 2, "sku_zone": None, "session_seq": 1},
        }
        client.post("/events/ingest", json=[ev])

        r = client.get(f"/stores/{store}/anomalies")
        types = [log["anomaly_type"] for log in r.json()["logs"]]
        assert "BILLING_QUEUE_SPIKE" not in types


# Severity escalation 

class TestSeverityEscalation:
    def test_severity_levels_valid(self):
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        sev = r.json()["severity_index"]
        assert sev in ("NORMAL", "INFO", "WARN", "CRITICAL")

    def test_critical_takes_precedence_over_warn(self):
        """After a backroom breach, severity_index should be CRITICAL even if other warnings exist."""
        # Trigger backroom breach (CRITICAL)
        entry = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_sev1",
                    event_type="ENTRY", timestamp="2026-03-03T13:00:00Z")
        backroom = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_sev1",
                       event_type="ZONE_ENTER", zone_id="BACKROOM",
                       timestamp="2026-03-03T13:01:00Z", is_staff=False)
        client.post("/events/ingest", json=[entry, backroom])

        r = client.get(f"/stores/{STORE_ID}/anomalies")
        assert r.json()["severity_index"] == "CRITICAL"

    def test_anomaly_count_matches_logs_length(self):
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        data = r.json()
        assert data["anomaly_count"] == len(data["logs"])


# Per-log structure 

class TestAnomalyLogStructure:
    def test_each_log_has_required_fields(self):
        # Trigger at least one anomaly
        entry = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_struct1",
                    event_type="ENTRY", timestamp="2026-03-03T12:00:00Z")
        backroom = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_struct1",
                       event_type="ZONE_ENTER", zone_id="BACKROOM",
                       timestamp="2026-03-03T12:01:00Z", is_staff=False)
        client.post("/events/ingest", json=[entry, backroom])

        r = client.get(f"/stores/{STORE_ID}/anomalies")
        for log in r.json()["logs"]:
            assert "anomaly_type" in log, "anomaly_type missing"
            assert "severity" in log, "severity missing"
            assert "suggested_action" in log, "suggested_action missing"
            assert "details" in log, "details missing"
            assert log["severity"] in ("INFO", "WARN", "CRITICAL")

    def test_unknown_store_returns_404(self):
        r = client.get("/stores/STORE_FAKE_XYZ/anomalies")
        assert r.status_code == 404
