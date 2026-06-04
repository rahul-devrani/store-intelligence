from __future__ import annotations

import datetime
import time
from typing import Any, Dict

from app.database import get_db_connection

STALE_THRESHOLD_SEC = 600  


def _lag_seconds(latest_ts_offset: float) -> float:
    """
    Convert a seconds-since-midnight timestamp (as stored in raw_events)
    to an approximate wall-clock lag in seconds.

    We reconstruct today's UTC midnight as an epoch and add the stored offset.
    This avoids the `time.time() % 86400` bug that returns wrong values
    whenever UTC time and the event's same-day seconds are in different
    calendar days.
    """
    today_midnight = datetime.datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    latest_epoch = today_midnight + latest_ts_offset
    return float(time.time()) - latest_epoch


class HealthChecker:
    @staticmethod
    def audit_health() -> Dict[str, Any]:
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("SELECT MAX(timestamp) AS latest FROM raw_events")
            row = cur.fetchone()
            global_latest = row["latest"] if row else None

            cur.execute("""
                SELECT store_id, MAX(timestamp) AS latest
                FROM raw_events
                GROUP BY store_id
            """)
            store_statuses: Dict[str, Any] = {}
            for r in cur.fetchall():
                sid = r["store_id"]
                ts = r["latest"]
                if ts is not None:
                    lag = _lag_seconds(ts)
                    feed_status = "STALE_FEED" if lag > STALE_THRESHOLD_SEC else "OK"
                else:
                    lag = None
                    feed_status = "NO_DATA"
                store_statuses[sid] = {
                    "last_event_timestamp": ts,
                    "feed_lag_seconds": round(lag, 1) if lag is not None else None,
                    "feed_status": feed_status,
                }

            cur.execute("SELECT COUNT(*) AS cnt FROM raw_events")
            total_events = cur.fetchone()["cnt"] or 0

            conn.close()

            return {
                "status": "healthy",
                "datastore_reachable": True,
                "latest_event_timestamp": global_latest,
                "total_events_stored": total_events,
                "stores": store_statuses,
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "datastore_reachable": False,
                "error": str(e),
                "stores": {},
            }
