"""
app/metrics.py — Real-time store metrics calculator.

Provides:
  - MetricsCalculator.calculate_store_metrics(store_id) → dict
  - get_pos_analytics(store_id, window_start, window_end) → (status, revenue, converted_count)

Conversion method:
  "temporal_overlap"  — CCTV billing zone timestamp matched to POS transaction window
  "approximation"     — POS order count divided by footfall (no CCTV-POS time alignment)
  "unavailable"       — no data to compute
"""
from __future__ import annotations

import csv
import os
import time
from typing import Any, Dict, Optional, Tuple

from app.database import get_db_connection

POS_FILE = os.environ.get("POS_FILE", os.environ.get("SALES_CSV_PATH", "data/pos_transactions.csv"))

STORE_POS_MAPPING = {
    "STORE_BLR_001": "ST1008",
    "STORE_BLR_002": "ST1009",
}
# How many seconds before a POS transaction timestamp a billing zone visit counts as converted
POS_CORRELATION_WINDOW_SEC = 300  # 5-minute window


def _parse_iso_to_seconds(ts_str: str) -> Optional[float]:
    """Parse ISO-8601 UTC string → seconds-since-midnight float. Returns None on failure."""
    try:
        time_part = ts_str.split("T")[-1].replace("Z", "").split(".")[0]
        h, m, s = map(int, time_part.split(":"))
        return float(h * 3600 + m * 60 + s)
    except Exception:
        return None


def _load_pos_transactions(store_id: str) -> list:
    """
    Load POS transactions for a store from CSV.
    Expected columns: store_id, transaction_id, timestamp, basket_value_inr
    Returns list of dicts with keys: timestamp_seconds, basket_value
    """
    candidates = [
        POS_FILE,
        "data/pos_transactions.csv",
        "/app/data/pos_transactions.csv",
        "pos_transactions.csv",
    ]
    filepath = None
    for c in candidates:
        if os.path.exists(c):
            filepath = c
            break
    if not filepath:
        return []

    transactions = []
    try:
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                
                mapped_store = STORE_POS_MAPPING.get(store_id, store_id)

                row_store = row.get("store_id", "").strip()

                if row_store != mapped_store:
                    continue
                ts_str = row.get("timestamp", "")
                
                if not ts_str:
                    order_date = row.get("order_date", "").strip()
                    order_time = row.get("order_time", "").strip()
                    if order_date and order_time:
                        ts_str = f"{order_date}T{order_time}Z"
                ts_sec = _parse_iso_to_seconds(ts_str)
                if ts_sec is None:
                    continue
                try:

                raw_val = row.get("basket_value_inr") or row.get("total_amount", 0)
                basket = float(raw_val or 0)

                
                if not ts_str:
                    order_date = row.get("order_date", "").strip()
                    order_time = row.get("order_time", "").strip()
                    if order_date and order_time:
                        ts_str = f"{order_date}T{order_time}Z"


                except ValueError:
                    basket = 0.0
                transactions.append({"timestamp_seconds": ts_sec, "basket_value": basket})
    except Exception as e:
        print(f"[Metrics] POS file read error: {e}")
    return transactions


def get_pos_analytics(
    store_id: str,
    window_start: float,
    window_end: float,
) -> Tuple[str, float, int]:
    """
    Correlate POS transactions with CCTV billing zone visits.

    Logic: A visitor who was in the BILLING zone within POS_CORRELATION_WINDOW_SEC
    before a transaction timestamp is counted as a converted visitor.

    Returns: (status, total_revenue, converted_visitor_count)
      status: "CONFIDENT" | "APPROXIMATION" | "NO_DATA"
    """
    if window_start == 0.0 and window_end == 0.0:
        return ("NO_DATA", 0.0, 0)

    pos_txns = _load_pos_transactions(store_id)
    if not pos_txns:
        return ("NO_DATA", 0.0, 0)

    conn = get_db_connection()
    cur = conn.cursor()

    
    cur.execute("""
        SELECT DISTINCT visitor_id, timestamp
        FROM raw_events
        WHERE store_id = ?
          AND zone_id = 'BILLING'
          AND is_staff = 0
          AND event_type IN ('ZONE_EXIT', 'ZONE_ENTER', 'ZONE_DWELL', 'BILLING_QUEUE_JOIN')
        ORDER BY timestamp
    """, (store_id,))
    billing_visits = cur.fetchall()
    conn.close()

    if not billing_visits:
        
        total_rev = sum(t["basket_value"] for t in pos_txns)
        return ("APPROXIMATION", round(total_rev, 2), len(pos_txns))

    converted_visitors = set()
    total_revenue = 0.0

    for txn in pos_txns:
        txn_ts = txn["timestamp_seconds"]
        total_revenue += txn["basket_value"]
        for row in billing_visits:
            visit_ts = row["timestamp"]
            
            if 0 <= (txn_ts - visit_ts) <= POS_CORRELATION_WINDOW_SEC:
                converted_visitors.add(row["visitor_id"])

    return ("CONFIDENT", round(total_revenue, 2), len(converted_visitors))


class MetricsCalculator:
    @staticmethod
    def calculate_store_metrics(store_id: str) -> Dict[str, Any]:
        conn = get_db_connection()
        cur = conn.cursor()

        # Footfall: unique non-staff visitors 
        cur.execute("""
            SELECT COUNT(DISTINCT visitor_id) AS cnt
            FROM visitors
            WHERE store_id = ? AND is_staff = 0
        """, (store_id,))
        footfall = cur.fetchone()["cnt"] or 0

        # Checkout visitors: unique non-staff who reached BILLING 
        cur.execute("""
            SELECT COUNT(DISTINCT visitor_id) AS cnt
            FROM raw_events
            WHERE store_id = ? AND zone_id = 'BILLING' AND is_staff = 0
        """, (store_id,))
        checkout_visitors = cur.fetchone()["cnt"] or 0

        #  Average checkout dwell 
        cur.execute("""
            SELECT AVG(dwell_ms) AS avg_dwell
            FROM raw_events
            WHERE store_id = ? AND zone_id = 'BILLING'
              AND is_staff = 0 AND dwell_ms > 0
        """, (store_id,))
        row = cur.fetchone()
        avg_checkout_dwell_sec = round((row["avg_dwell"] or 0) / 1000.0, 1)

        #  Average dwell per zone 
        cur.execute("""
            SELECT zone_id, AVG(dwell_ms) AS avg_dwell
            FROM raw_events
            WHERE store_id = ? AND zone_id IS NOT NULL
              AND is_staff = 0 AND dwell_ms > 0
            GROUP BY zone_id
        """, (store_id,))
        avg_dwell_per_zone = {
            r["zone_id"]: round((r["avg_dwell"] or 0) / 1000.0, 1)
            for r in cur.fetchall()
        }

        # Queue depth 
        cur.execute("""
            SELECT AVG(queue_depth) AS avg_q, MAX(queue_depth) AS max_q
            FROM raw_events
            WHERE store_id = ? AND queue_depth IS NOT NULL
        """, (store_id,))
        q_row = cur.fetchone()
        avg_queue_depth = round(q_row["avg_q"] or 0.0, 1)
        max_queue_depth = q_row["max_q"] or 0

        # Billing abandonment 
        cur.execute("""
            SELECT COUNT(DISTINCT visitor_id) AS cnt
            FROM raw_events
            WHERE store_id = ? AND event_type = 'BILLING_QUEUE_ABANDON' AND is_staff = 0
        """, (store_id,))
        abandoned = cur.fetchone()["cnt"] or 0
        abandonment_pct = round((abandoned / checkout_visitors * 100) if checkout_visitors > 0 else 0.0, 1)

        # REENTRY count 
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM raw_events
            WHERE store_id = ? AND event_type = 'REENTRY'
        """, (store_id,))
        reentry_count = cur.fetchone()["cnt"] or 0

        # Time window for POS correlation 
        cur.execute(
            "SELECT MIN(timestamp) AS st, MAX(timestamp) AS et FROM raw_events WHERE store_id = ?",
            (store_id,),
        )
        bounds = cur.fetchone()
        window_start = bounds["st"] or 0.0
        window_end = bounds["et"] or 0.0

        # Diagnostics 
        cur.execute("SELECT COUNT(*) AS cnt FROM raw_events WHERE store_id = ?", (store_id,))
        total_events = cur.fetchone()["cnt"] or 0

        cur.execute("""
            SELECT COUNT(DISTINCT visitor_id) AS cnt
            FROM raw_events WHERE store_id = ?
        """, (store_id,))
        total_unique = cur.fetchone()["cnt"] or 0

        conn.close()

        density_ratio = round(total_events / total_unique, 2) if total_unique > 0 else 0.0
        frag_status = "HIGH" if density_ratio > 50 else "NORMAL"

        # POS analytics 
        pos_status, pos_revenue, converted_count = get_pos_analytics(store_id, window_start, window_end)

        if pos_status == "CONFIDENT" and footfall > 0:
            conversion_rate = round((converted_count / footfall) * 100, 1)
            conversion_method = "temporal_overlap"
            conversion_note = None
        elif pos_status == "APPROXIMATION" and footfall > 0 and converted_count > 0:
            conversion_rate = round((converted_count / footfall) * 100, 1)
            conversion_method = "approximation"
            conversion_note = (
                "POS order count divided by CCTV footfall. "
                "Temporal alignment unavailable; this is an estimate."
            )
        else:
            conversion_rate = None
            conversion_method = "unavailable"
            conversion_note = (
                f"Cannot compute: footfall={footfall}, "
                f"pos_status={pos_status}, converted={converted_count}. "
                "Ingest CCTV events and ensure POS file is accessible."
            )

        pos_analytics: Dict[str, Any] = {
            "orders_count_today": converted_count,
            "net_revenue_inr_today": pos_revenue,
            "conversion_rate_percentage": conversion_rate,
            "conversion_method": conversion_method,
        }
        if conversion_note:
            pos_analytics["conversion_note"] = conversion_note

        return {
            "store_id": store_id,
            "video_analytics": {
                "footfall_count": footfall,
                "checkout_visitors": checkout_visitors,
                "average_checkout_dwell_seconds": avg_checkout_dwell_sec,
                "avg_dwell_per_zone_seconds": avg_dwell_per_zone,
                "average_queue_depth": avg_queue_depth,
                "max_queue_depth": max_queue_depth,
                "billing_abandonment_count": abandoned,
                "billing_abandonment_percentage": abandonment_pct,
                "reentry_count": reentry_count,
            },
            "pos_analytics": pos_analytics,
            "diagnostics": {
                "total_events_ingested": total_events,
                "total_unique_visitors_tracked": total_unique,
                "event_density_ratio": density_ratio,
                "track_fragmentation_status": frag_status,
            },
        }
