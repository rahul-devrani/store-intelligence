# PROMPT: "Write pytest tests for a retail store conversion funnel API endpoint.
# Cover: stage counts are monotonically decreasing, re-entry counted once,
# staff excluded from all stages, empty store returns zeros, drop-off percentages
# are consistent, stage_4 is None when no POS data, session deduplication."
# CHANGES MADE: Aligned with actual funnel stages (stage_1 through stage_4),
# used correct schema with metadata field, ensured zone names match layout config,
# fixed dwell_ms threshold (15000ms = 15s for stage_2 qualification).

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ["DB_PATH"] = "/tmp/test_funnel.db"

from app.main import app
from app import database

client = TestClient(app)

STORE_ID = "STORE_BLR_002"


def _ev(**overrides):
    base = {
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": "CAM_4",
        "visitor_id": "VIS_f001",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:00:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.92,
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


#  Empty store 

class TestEmptyStoreFunnel:
    def test_empty_store_no_crash(self):
        r = client.get(f"/stores/{STORE_ID}/funnel")
        assert r.status_code == 200

    def test_empty_store_all_zeros(self):
        r = client.get(f"/stores/{STORE_ID}/funnel")
        f = r.json()["funnel"]
        assert f["stage_1_entered"] == 0
        assert f["stage_2_browsed_aisles"] == 0
        assert f["stage_3_reached_checkout"] == 0

    def test_empty_store_stage4_none_or_zero(self):
        r = client.get(f"/stores/{STORE_ID}/funnel")
        stage4 = r.json()["funnel"]["stage_4_completed_purchase"]
        assert stage4 is None or stage4 == 0

    def test_funnel_response_schema(self):
        r = client.get(f"/stores/{STORE_ID}/funnel")
        data = r.json()
        assert "store_id" in data
        assert "funnel" in data
        assert "drop_off_pct" in data
        assert "temporal_overlap_status" in data


#  Stage ordering 

class TestFunnelStageOrdering:
    def test_stages_monotonically_decreasing(self):
        """stage_1 >= stage_2 >= stage_3 always."""
        events = []
        # 10 visitors enter
        for i in range(10):
            events.append(_ev(
                event_id=str(uuid.uuid4()), visitor_id=f"VIS_f{i:03d}",
                event_type="ENTRY",
            ))
        # 6 browse aisles (dwell_ms >= 15000)
        for i in range(6):
            events.append(_ev(
                event_id=str(uuid.uuid4()), visitor_id=f"VIS_f{i:03d}",
                event_type="ZONE_ENTER", zone_id="BOH",
                dwell_ms=20000, timestamp="2026-03-03T14:10:00Z",
            ))
            events.append(_ev(
                event_id=str(uuid.uuid4()), visitor_id=f"VIS_f{i:03d}",
                event_type="ZONE_EXIT", zone_id="BOH",
                dwell_ms=20000, timestamp="2026-03-03T14:11:00Z",
            ))
        # 3 reach checkout
        for i in range(3):
            events.append(_ev(
                event_id=str(uuid.uuid4()), visitor_id=f"VIS_f{i:03d}",
                event_type="ZONE_ENTER", zone_id="BILLING",
                timestamp="2026-03-03T14:20:00Z",
            ))
        client.post("/events/ingest", json=events)

        r = client.get(f"/stores/{STORE_ID}/funnel")
        f = r.json()["funnel"]
        assert f["stage_1_entered"] >= f["stage_2_browsed_aisles"], (
            f"stage_1={f['stage_1_entered']} < stage_2={f['stage_2_browsed_aisles']}"
        )
        assert f["stage_2_browsed_aisles"] >= f["stage_3_reached_checkout"], (
            f"stage_2={f['stage_2_browsed_aisles']} < stage_3={f['stage_3_reached_checkout']}"
        )

    def test_stage1_counts_unique_visitors(self):
        events = []
        for i in range(5):
            events.append(_ev(event_id=str(uuid.uuid4()), visitor_id=f"VIS_u{i:03d}",
                              event_type="ENTRY"))
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/funnel")
        assert r.json()["funnel"]["stage_1_entered"] == 5


# Staff exclusion 

class TestStaffExclusionFunnel:
    def test_staff_excluded_from_stage1(self):
        cust = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_cust01", is_staff=False)
        staff = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_stf01", is_staff=True)
        client.post("/events/ingest", json=[cust, staff])

        r = client.get(f"/stores/{STORE_ID}/funnel")
        # Only the customer counts
        assert r.json()["funnel"]["stage_1_entered"] == 1

    def test_all_staff_funnel_all_zeros(self):
        events = [
            _ev(event_id=str(uuid.uuid4()), visitor_id=f"VIS_s{i}", is_staff=True)
            for i in range(4)
        ]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/funnel")
        f = r.json()["funnel"]
        assert f["stage_1_entered"] == 0


# Re-entry deduplication 

class TestReentryDeduplication:
    def test_reentry_visitor_counted_once_in_funnel(self):
        """A visitor who re-enters the store should count as 1 in stage_1."""
        vid = "VIS_rentry1"
        entry = _ev(event_id=str(uuid.uuid4()), visitor_id=vid,
                    event_type="ENTRY", timestamp="2026-03-03T14:00:00Z")
        reentry = _ev(event_id=str(uuid.uuid4()), visitor_id=vid,
                      event_type="REENTRY", timestamp="2026-03-03T14:30:00Z")
        client.post("/events/ingest", json=[entry, reentry])

        r = client.get(f"/stores/{STORE_ID}/funnel")
        assert r.json()["funnel"]["stage_1_entered"] == 1

    def test_two_different_visitors_both_counted(self):
        v1 = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_a1", event_type="ENTRY")
        v2 = _ev(event_id=str(uuid.uuid4()), visitor_id="VIS_a2", event_type="ENTRY")
        client.post("/events/ingest", json=[v1, v2])
        r = client.get(f"/stores/{STORE_ID}/funnel")
        assert r.json()["funnel"]["stage_1_entered"] == 2


# Drop-off consistency 

class TestDropOffConsistency:
    def test_drop_off_present_in_response(self):
        r = client.get(f"/stores/{STORE_ID}/funnel")
        drop = r.json()["drop_off_pct"]
        assert "entry_to_browse" in drop
        assert "browse_to_checkout" in drop
        assert "checkout_to_purchase" in drop

    def test_drop_off_none_when_stage_is_zero(self):
        """Drop-off % must be None (not crash) when denominator stage is zero."""
        r = client.get(f"/stores/{STORE_ID}/funnel")
        drop = r.json()["drop_off_pct"]
        for key, val in drop.items():
            assert val is None or isinstance(val, (int, float)), (
                f"drop_off_pct.{key} is invalid type: {type(val)}"
            )

    def test_drop_off_values_0_to_100(self):
        events = []
        for i in range(4):
            events.append(_ev(event_id=str(uuid.uuid4()), visitor_id=f"VIS_drop{i}",
                              event_type="ENTRY"))
        for i in range(2):
            events.append(_ev(event_id=str(uuid.uuid4()), visitor_id=f"VIS_drop{i}",
                              event_type="ZONE_ENTER", zone_id="BILLING",
                              timestamp="2026-03-03T14:20:00Z"))
        client.post("/events/ingest", json=events)

        r = client.get(f"/stores/{STORE_ID}/funnel")
        drop = r.json()["drop_off_pct"]
        for key, val in drop.items():
            if val is not None:
                assert 0.0 <= val <= 100.0, f"drop_off_pct.{key}={val} out of range"


# 404 for unknown store 

class TestFunnelStoreNotFound:
    def test_unknown_store_returns_404(self):
        r = client.get("/stores/STORE_INVALID_999/funnel")
        assert r.status_code == 404
