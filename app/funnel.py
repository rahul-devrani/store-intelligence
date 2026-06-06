from __future__ import annotations

from typing import Any, Dict, Optional

from app.database import get_db_connection
from app.metrics import get_pos_analytics


class FunnelCalculator:
    @staticmethod
    def calculate_funnel(store_id: str) -> Dict[str, Any]:
        conn = get_db_connection()
        cur = conn.cursor()

        #  unique customer entrances (ENTRY + REENTRY both count once per visitor)
        cur.execute("""
            SELECT COUNT(DISTINCT visitor_id) AS cnt
            FROM visitors
            WHERE store_id = ? AND is_staff = 0
        """, (store_id,))
        stage_1 = cur.fetchone()["cnt"] or 0

        # unique visitors who dwelled 15+ seconds in any product zone
        cur.execute("""
            SELECT COUNT(DISTINCT visitor_id) AS cnt
            FROM raw_events
            WHERE store_id = ?
              AND zone_id NOT IN (
'CASH_COUNTER',
'QUEUE_AREA',
'BACKROOM',
'ENTRANCE'
)
              AND zone_id IS NOT NULL
              AND dwell_ms >= 15000
              AND is_staff = 0
        """, (store_id,))
        stage_2 = cur.fetchone()["cnt"] or 0

        # unique customers who reached billing queue
        cur.execute("""
            SELECT COUNT(DISTINCT visitor_id) AS cnt
            FROM raw_events
            WHERE store_id = ? AND zone_id = 'CASH_COUNTER' AND is_staff = 0
        """, (store_id,))
        stage_3 = cur.fetchone()["cnt"] or 0

        # Video window for POS correlation
        cur.execute(
            "SELECT MIN(timestamp) AS st, MAX(timestamp) AS et FROM raw_events WHERE store_id = ?",
            (store_id,),
        )
        bounds = cur.fetchone()
        st_win = bounds["st"] or 0.0
        et_win = bounds["et"] or 0.0

        conn.close()

        # POS-correlated purchases
        status, _, converted_count = get_pos_analytics(store_id, st_win, et_win)
        stage_4: Optional[int] = converted_count if status == "CONFIDENT" else None

        def drop(a: Optional[int], b: Optional[int]) -> Optional[float]:
            if a is None or b is None or a == 0:
                return None
            return round((1 - b / a) * 100, 1)

        return {
            "store_id": store_id,
            "temporal_overlap_status": status,
            "funnel": {
                "stage_1_entered":            stage_1,
                "stage_2_browsed_aisles":     stage_2,
                "stage_3_reached_checkout":   stage_3,
                "stage_4_completed_purchase": stage_4,
            },
            "drop_off_pct": {
                "entry_to_browse":       drop(stage_1, stage_2),
                "browse_to_checkout":    drop(stage_2, stage_3),
                "checkout_to_purchase":  drop(stage_3, stage_4),
            },
        }
