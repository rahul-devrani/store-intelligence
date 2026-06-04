"""
app/sessions.py — Session management helpers.

Provides utilities to query and summarise visitor sessions
stored in the visitor_sessions table.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.database import get_db_connection


def get_active_sessions(store_id: str) -> List[Dict[str, Any]]:
    """
    Return all currently open (no end_time) customer sessions for a store.
    Excludes staff sessions.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT session_id, visitor_id, start_time
        FROM visitor_sessions
        WHERE store_id = ? AND end_time IS NULL AND is_staff = 0
        ORDER BY start_time
    """, (store_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_session_summary(store_id: str) -> Dict[str, Any]:
    """
    Return aggregate session statistics for a store:
      - total_sessions: all non-staff sessions
      - completed_sessions: sessions with end_time set
      - open_sessions: sessions still in-store
      - avg_session_duration_seconds: average for completed sessions
    """
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*)                                              AS total,
            SUM(CASE WHEN end_time IS NOT NULL THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN end_time IS NULL     THEN 1 ELSE 0 END) AS open,
            AVG(CASE WHEN end_time IS NOT NULL
                     THEN end_time - start_time END)             AS avg_duration
        FROM visitor_sessions
        WHERE store_id = ? AND is_staff = 0
    """, (store_id,))
    row = cur.fetchone()
    conn.close()

    return {
        "store_id": store_id,
        "total_sessions": row["total"] or 0,
        "completed_sessions": row["completed"] or 0,
        "open_sessions": row["open"] or 0,
        "avg_session_duration_seconds": round(row["avg_duration"] or 0.0, 1),
    }


def close_stale_sessions(store_id: str, cutoff_seconds: float) -> int:
    """
    Mark sessions as closed if their start_time is older than cutoff_seconds
    and they have no end_time. Used for cleanup when clips end abruptly.
    Returns the number of sessions closed.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE visitor_sessions
        SET end_time = start_time + ?
        WHERE store_id = ?
          AND end_time IS NULL
          AND start_time < (SELECT MAX(timestamp) FROM raw_events WHERE store_id = ?) - ?
    """, (cutoff_seconds, store_id, store_id, cutoff_seconds))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected


def get_visitor_session_history(store_id: str, visitor_id: str) -> List[Dict[str, Any]]:
    """
    Return all sessions for a specific visitor in a store, ordered by start time.
    Useful for REENTRY detection and funnel deduplication auditing.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT session_id, start_time, end_time, is_staff, unauthorized_backroom
        FROM visitor_sessions
        WHERE store_id = ? AND visitor_id = ?
        ORDER BY start_time
    """, (store_id, visitor_id))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
