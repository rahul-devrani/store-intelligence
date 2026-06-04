"""
app/heatmap.py — Zone-based heatmap computation helpers.

Provides aggregate zone visit frequency and average dwell, normalised
to a 0–100 scale ready for grid heatmap rendering.
Used by GET /stores/{id}/heatmap when zone-level (not spatial grid) data
is needed, and as a helper for the dashboard.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.database import get_db_connection


def get_zone_heatmap(store_id: str) -> Dict[str, Any]:
    """
    Compute per-zone visit frequency and average dwell for a store,
    normalised to 0–100.

    Returns:
      {
        "store_id": str,
        "zones": {
          "SKINCARE_WALL": {"visit_count": 12, "avg_dwell_seconds": 45.2, "score": 100},
          ...
        },
        "data_confidence": "OK" | "LOW",
        "session_count": int,
      }
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # Count unique visitor+zone combinations and average dwell per zone
    cur.execute("""
        SELECT
            zone_id,
            COUNT(DISTINCT visitor_id)  AS visit_count,
            AVG(dwell_ms)               AS avg_dwell_ms
        FROM raw_events
        WHERE store_id = ?
          AND zone_id IS NOT NULL
          AND is_staff = 0
        GROUP BY zone_id
    """, (store_id,))
    rows = cur.fetchall()

    # Session count for confidence flag
    cur.execute("""
        SELECT COUNT(DISTINCT session_id) AS cnt
        FROM visitor_sessions
        WHERE store_id = ? AND is_staff = 0
    """, (store_id,))
    session_count = cur.fetchone()["cnt"] or 0
    conn.close()

    if not rows:
        return {
            "store_id": store_id,
            "zones": {},
            "data_confidence": "LOW",
            "session_count": 0,
        }

    max_visits = max(r["visit_count"] for r in rows) or 1

    zones: Dict[str, Any] = {}
    for r in rows:
        score = round((r["visit_count"] / max_visits) * 100)
        avg_dwell_sec = round((r["avg_dwell_ms"] or 0) / 1000.0, 1)
        zones[r["zone_id"]] = {
            "visit_count": r["visit_count"],
            "avg_dwell_seconds": avg_dwell_sec,
            "score": score,
        }

    data_confidence = "OK" if session_count >= 20 else "LOW"

    return {
        "store_id": store_id,
        "zones": zones,
        "data_confidence": data_confidence,
        "session_count": session_count,
    }


def get_spatial_heatmap(store_id: str) -> Dict[str, Any]:
    """
    Retrieve the 10×10 spatial grid heatmap from the heatmap_bins table.
    Returns the raw and normalised (0–100) grids.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT x_grid, y_grid, frequency_count FROM heatmap_bins WHERE store_id = ?",
        (store_id,),
    )
    rows = cur.fetchall()
    conn.close()

    grid = [[0] * 10 for _ in range(10)]
    max_val = 0
    for r in rows:
        x, y, cnt = r["x_grid"], r["y_grid"], r["frequency_count"]
        if 0 <= x <= 9 and 0 <= y <= 9:
            grid[y][x] = cnt
            max_val = max(max_val, cnt)

    norm_grid = [
        [round((v / max_val) * 100) if max_val > 0 else 0 for v in row]
        for row in grid
    ]

    total_hits = sum(sum(r) for r in grid)
    data_confidence = "OK" if total_hits >= 20 else "LOW"

    return {
        "store_id": store_id,
        "grid_resolution": "10x10",
        "spatial_matrix": norm_grid,
        "raw_matrix": grid,
        "data_confidence": data_confidence,
    }
