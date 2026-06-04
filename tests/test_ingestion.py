# PROMPT: "Write pytest tests for a FastAPI event ingestion endpoint covering:
# idempotency by event_id, batch size limits (0 and 501), partial-success on
# mixed valid/invalid events, staff flag storage, visitor upsert, session
# creation on ENTRY/REENTRY, session close on EXIT."
# CHANGES MADE: Used correct Pydantic EventPayload schema (visitor_id not
# person_id, metadata object required), aligned DB field names with database.py,
# added fresh_db fixture for test isolation, fixed timestamp format to ISO-8601.

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ["DB_PATH"] = "/tmp/test_ingestion.db"

from app.main import app
from app import database

client = TestClient(app)

STORE_ID = "STORE_BLR_001"


def _ev(**overrides):
    base = {
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": "CAM_3",
        "visitor_id": "VIS_test001",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.95,
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


#  Basic ingest 

class TestBasicIngest:
    def test_single_event_success(self):
        r = client.post("/events/ingest", json=[_ev()])
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["processed"] == 1
        assert data["duplicates_skipped"] == 0
        assert data["malformed_skipped"] == 0

    def test_response_contains_all_keys(self):
        r = client.post("/events/ingest", json=[_ev()])
        data = r.json()
        for key in ("status", "processed", "duplicates_skipped", "malformed_skipped"):
            assert key in data, f"Missing key: {key}"

    def test_multiple_unique_events(self):
        events = [_ev(event_id=str(uuid.uuid4()), visitor_id=f"VIS_{i:04d}") for i in range(5)]
        r = client.post("/events/ingest", json=events)
        assert r.status_code == 200
        assert r.json()["processed"] == 5


# Batch size constraints 

class TestBatchConstraints:
    def test_empty_batch_rejected(self):
        r = client.post("/events/ingest", json=[])
        assert r.status_code == 400

    def test_501_events_rejected(self):
        batch = [_ev(event_id=str(uuid.uuid4()), visitor_id=f"V{i}") for i in range(501)]
        r = client.post("/events/ingest", json=batch)
        assert r.status_code == 400

    def test_exactly_500_events_accepted(self):
        batch = [_ev(event_id=str(uuid.uuid4()), visitor_id=f"V{i:04d}") for i in range(500)]
        r = client.post("/events/ingest", json=batch)
        assert r.status_code == 200
        assert r.json()["processed"] == 500


#  Idempotency 

class TestIdempotency:
    def test_same_event_id_deduplicated(self):
        ev = _ev()
        r1 = client.post("/events/ingest", json=[ev])
        r2 = client.post("/events/ingest", json=[ev])
        assert r1.json()["processed"] == 1
        assert r2.json()["duplicates_skipped"] == 1
        assert r2.json()["processed"] == 0

    def test_idempotent_batch_with_mix(self):
        ev_dup = _ev()
        ev_new = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_new1")
        client.post("/events/ingest", json=[ev_dup])
        r = client.post("/events/ingest", json=[ev_dup, ev_new])
        assert r.json()["duplicates_skipped"] == 1
        assert r.json()["processed"] == 1

    def test_triple_ingest_still_counts_one(self):
        ev = _ev()
        for _ in range(3):
            client.post("/events/ingest", json=[ev])
        # Check raw_events has only one row for this event_id
        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM raw_events WHERE event_id = ?", (ev["event_id"],))
        count = cur.fetchone()["cnt"]
        conn.close()
        assert count == 1


#  Staff flag 

class TestStaffFlag:
    def test_staff_event_stored_with_is_staff_true(self):
        ev = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_staff1", is_staff=True)
        r = client.post("/events/ingest", json=[ev])
        assert r.status_code == 200

        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT is_staff FROM raw_events WHERE event_id = ?", (ev["event_id"],))
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row["is_staff"] == 1

    def test_once_staff_always_staff_in_visitor_registry(self):
        """If a visitor is flagged as staff in any event, visitors table reflects that."""
        vid = "VIS_mixed1"
        ev_cust = _ev(event_id=str(uuid.uuid4()), visitor_id=vid, is_staff=False)
        ev_staff = _ev(event_id=str(uuid.uuid4()), visitor_id=vid, is_staff=True,
                       timestamp="2026-03-03T15:00:00Z")
        client.post("/events/ingest", json=[ev_cust, ev_staff])

        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT is_staff FROM visitors WHERE visitor_id = ? AND store_id = ?",
                    (vid, STORE_ID))
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row["is_staff"] == 1


#  Session lifecycle 

class TestSessionLifecycle:
    def test_entry_creates_session(self):
        vid = "VIS_sess01"
        ev = _ev(event_id=str(uuid.uuid4()), visitor_id=vid, event_type="ENTRY")
        client.post("/events/ingest", json=[ev])

        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM visitor_sessions WHERE visitor_id = ? AND store_id = ?",
                    (vid, STORE_ID))
        count = cur.fetchone()["cnt"]
        conn.close()
        assert count >= 1

    def test_exit_closes_session(self):
        vid = "VIS_sess02"
        entry = _ev(event_id=str(uuid.uuid4()), visitor_id=vid, event_type="ENTRY",
                    timestamp="2026-03-03T14:00:00Z")
        exit_ev = _ev(event_id=str(uuid.uuid4()), visitor_id=vid, event_type="EXIT",
                      timestamp="2026-03-03T14:30:00Z")
        client.post("/events/ingest", json=[entry, exit_ev])

        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT end_time FROM visitor_sessions
            WHERE visitor_id = ? AND store_id = ?
            ORDER BY start_time DESC LIMIT 1
        """, (vid, STORE_ID))
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row["end_time"] is not None

    def test_reentry_creates_new_session(self):
        vid = "VIS_sess03"
        entry = _ev(event_id=str(uuid.uuid4()), visitor_id=vid, event_type="ENTRY",
                    timestamp="2026-03-03T14:00:00Z")
        reentry = _ev(event_id=str(uuid.uuid4()), visitor_id=vid, event_type="REENTRY",
                      timestamp="2026-03-03T14:45:00Z")
        client.post("/events/ingest", json=[entry, reentry])

        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM visitor_sessions WHERE visitor_id = ? AND store_id = ?",
                    (vid, STORE_ID))
        count = cur.fetchone()["cnt"]
        conn.close()
        assert count == 2


# Queue depth storage 

class TestQueueDepth:
    def test_queue_depth_stored_from_metadata(self):
        ev = _ev(
            event_id=str(uuid.uuid4()),
            visitor_id="VIS_q001",
            event_type="BILLING_QUEUE_JOIN",
            zone_id="BILLING",
            metadata={"queue_depth": 3, "sku_zone": None, "session_seq": 2},
        )
        client.post("/events/ingest", json=[ev])

        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT queue_depth FROM raw_events WHERE event_id = ?", (ev["event_id"],))
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row["queue_depth"] == 3

    def test_null_queue_depth_stored_as_null(self):
        ev = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_q002")
        client.post("/events/ingest", json=[ev])

        conn = database.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT queue_depth FROM raw_events WHERE event_id = ?", (ev["event_id"],))
        row = cur.fetchone()
        conn.close()
        assert row["queue_depth"] is None
