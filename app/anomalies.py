from __future__ import annotations

import time
from typing import Any, Dict, List

from app.database import get_db_connection

_DEFAULTS: Dict[str, Any] = {
    "QUEUE_SPIKE_THRESHOLD": 5,       # queue_depth above which we raise a spike alert
    "DEAD_ZONE_WINDOW_SEC": 1800,     # 30 minutes with no visits = dead zone
    "STALE_FEED_LAG_SEC": 600,        # 10-minute lag triggers STALE_FEED
    "CONVERSION_DROP_THRESHOLD": 0.5, # conversion 50% below 7-day average
}


def _load_thresholds(store_id: str) -> Dict[str, Any]:
    """
    Load anomaly thresholds from the store layout config (if present),
    falling back to defaults.  Allows per-store tuning without code changes.

    Store layout entry format:
        "anomaly_config": {
            "QUEUE_SPIKE_THRESHOLD": 8,
            "DEAD_ZONE_WINDOW_SEC": 900
        }
    """
    try:
        import json, os
        path = os.environ.get("LAYOUT_FILE", "/app/data/store_layout.json")
        with open(path) as f:
            data = json.load(f)
        overrides = data.get(store_id, {}).get("anomaly_config", {})
    except Exception:
        overrides = {}

    merged = {**_DEFAULTS, **overrides}
    return merged


class AnomalyDetector:
    @staticmethod
    def detect_anomalies(store_id: str) -> Dict[str, Any]:
        thresholds = _load_thresholds(store_id)
        QUEUE_SPIKE_THRESHOLD = int(thresholds["QUEUE_SPIKE_THRESHOLD"])
        DEAD_ZONE_WINDOW_SEC = float(thresholds["DEAD_ZONE_WINDOW_SEC"])
        STALE_FEED_LAG_SEC = float(thresholds["STALE_FEED_LAG_SEC"])

        conn = get_db_connection()
        cur = conn.cursor()
        alarms: List[Dict[str, Any]] = []

        # Unauthorized backroom access 
        cur.execute("""
            SELECT visitor_id,start_time
            FROM visitor_sessions
            WHERE store_id=?
            AND unauthorized_backroom=1
            AND is_staff=0
        """, (store_id,))
        
        for row in cur.fetchall():
            alarms.append({
                "anomaly_type": "UNAUTHORIZED_BACKROOM_ACCESS",
                "severity": "CRITICAL",
                "timestamp": row["start_time"],
                "details": f"Visitor '{row['visitor_id']}' entered a staff-only zone.",
                "suggested_action": "Dispatch security or verify staff badge status.",
            })

        # direct BOH/BACKROOM events
        cur.execute("""
            SELECT DISTINCT visitor_id, timestamp
            FROM raw_events
            WHERE store_id = ?
            AND zone_id IN ('BACKROOM', 'BOH')
            AND is_staff = 0
        """, (store_id,))

        for row in cur.fetchall():
            alarms.append({
                "anomaly_type": "UNAUTHORIZED_BACKROOM_ACCESS",
                "severity": "CRITICAL",
                "timestamp": row["timestamp"],
                "details": f"Visitor '{row['visitor_id']}' entered a staff-only zone.",
                "suggested_action": "Dispatch security or verify staff badge status.",
                })
        

        # Billing queue spike
        cur.execute("""
            SELECT MAX(queue_depth) AS max_q, AVG(queue_depth) AS avg_q
            FROM raw_events
            WHERE store_id = ? AND queue_depth IS NOT NULL
        """, (store_id,))

        row = cur.fetchone()

        if row is not None and row["max_q"] is not None and row["max_q"] > QUEUE_SPIKE_THRESHOLD:
            alarms.append({
                "anomaly_type": "BILLING_QUEUE_SPIKE",
                "severity": "WARN",
                "timestamp": None,
                "details": f"Queue depth peaked at {row['max_q']} (avg {round(row['avg_q'], 1)}).",
                "suggested_action": "Open additional billing counters or redirect staff.",
            })

        # Dead zone : no customer visits in configurable window 
        cur.execute(
            "SELECT MAX(timestamp) AS latest FROM raw_events WHERE store_id = ?",
            (store_id,),
        )
        latest_row = cur.fetchone()
        latest_ts = latest_row["latest"] if latest_row and latest_row["latest"] else None

        if latest_ts is not None:
            cur.execute("""
                SELECT zone_id, MAX(timestamp) AS last_visit
                FROM raw_events
                WHERE store_id = ? AND zone_id IS NOT NULL AND is_staff = 0
                GROUP BY zone_id
            """, (store_id,))
            for row in cur.fetchall():
                if row["last_visit"] is not None:
                    gap = latest_ts - row["last_visit"]
                    if gap >= DEAD_ZONE_WINDOW_SEC:
                        alarms.append({
                            "anomaly_type": "DEAD_ZONE",
                            "severity": "INFO",
                            "timestamp": row["last_visit"],
                            "details": (
                                f"Zone '{row['zone_id']}' had no customer visits "
                                f"for {int(gap // 60)} minutes."
                            ),
                            "suggested_action": "Check if zone is blocked or understocked.",
                        })

        # Stale feed detection
        if latest_ts is not None:
            now_utc = float(time.time())
        
            import datetime
            today_midnight = datetime.datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp()
            latest_epoch = today_midnight + latest_ts
            lag = now_utc - latest_epoch
            if lag > STALE_FEED_LAG_SEC:
                alarms.append({
                    "anomaly_type": "STALE_FEED",
                    "severity": "WARN",
                    "timestamp": latest_ts,
                    "details": f"No events received for {int(lag // 60)} minutes.",
                    "suggested_action": "Check camera connectivity and pipeline health.",
                })
        try:
            from app.metrics import MetricsCalculator

            metrics = MetricsCalculator.calculate_store_metrics(store_id)

            current = metrics["pos_analytics"].get(
                "conversion_rate_percentage"
            )

            baseline = 25.0

            if current is not None and current < baseline * 0.5:
                alarms.append({
                    "anomaly_type": "CONVERSION_DROP",
                    "severity": "WARN",
                    "timestamp": None,
                    "details":
                        f"Conversion dropped to {current}% "
                        f"(baseline {baseline}%)",
                    "suggested_action":
                        "Check staffing, queue depth and POS systems."
                })

        except Exception:
            pass


        conn.close()

        highest = "NORMAL"
        for a in alarms:
            if a["severity"] == "CRITICAL":
                highest = "CRITICAL"
                break
            if a["severity"] == "WARN":
                highest = "WARN"

        return {
            "store_id": store_id,
            "severity_index": highest,
            "anomaly_count": len(alarms),
            "logs": alarms,
        }
