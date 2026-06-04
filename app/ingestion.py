from __future__ import annotations

from typing import List, Tuple
from app.database import get_db_connection
from app.models import EventPayload


def _ts_to_seconds(ts: str) -> float:
    """Convert ISO-8601 UTC string to seconds-since-midnight float."""
    try:
        time_part = ts.split("T")[-1].replace("Z", "").split(".")[0]
        h, m, s = map(int, time_part.split(":"))
        return float(h * 3600 + m * 60 + s)
    except Exception:
        return 0.0


class IngestionManager:
    @staticmethod
    def process_batch(events: List[EventPayload]) -> Tuple[int, int, int]:
        """
        Idempotently insert a batch of events.
        Returns (success, duplicates, errors).
        """
        conn = get_db_connection()
        cur = conn.cursor()
        success = duplicates = errors = 0

        for ev in events:
            try:
                ts = _ts_to_seconds(ev.timestamp)
                is_staff_int = 1 if ev.is_staff else 0
                has_backroom = 1 if (ev.zone_id == "BACKROOM" and not ev.is_staff) else 0

                cur.execute("""
                    INSERT OR IGNORE INTO raw_events
                        (event_id, store_id, camera_id, visitor_id, event_type,
                         timestamp, zone_id, dwell_ms, is_staff, queue_depth)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    ev.event_id, ev.store_id, ev.camera_id, ev.visitor_id,
                    ev.event_type, ts, ev.zone_id, ev.dwell_ms,
                    is_staff_int, ev.metadata.queue_depth,
                ))

                if cur.rowcount == 0:
                    duplicates += 1
                    continue

                success += 1

                # Upsert visitor registry : once flagged as staff, always staff
                cur.execute("""
                    INSERT INTO visitors (visitor_id, store_id, is_staff)
                    VALUES (?, ?, ?)
                    ON CONFLICT(visitor_id, store_id) DO UPDATE SET
                        is_staff = MAX(is_staff, excluded.is_staff)
                """, (ev.visitor_id, ev.store_id, is_staff_int))

                # Session management
                # if ev.event_type in ("ENTRY", "REENTRY"):
                #     session_id = f"SESS_{ev.visitor_id}_{int(ts)}"
                #     cur.execute("""
                #         INSERT INTO visitor_sessions
                #             (session_id, store_id, visitor_id, start_time, is_staff, unauthorized_backroom)
                #         VALUES (?,?,?,?,?,?)
                #         ON CONFLICT(session_id) DO UPDATE SET
                #             start_time = MIN(start_time, excluded.start_time)
                #     """, (session_id, ev.store_id, ev.visitor_id, ts, is_staff_int, has_backroom))


                if ev.event_type in ("ENTRY", "REENTRY"):

                        cur.execute("""
                            SELECT 1
                            FROM visitor_sessions
                            WHERE visitor_id = ?
                            AND store_id = ?
                            AND end_time IS NULL
                            LIMIT 1
                        """, (ev.visitor_id, ev.store_id))

                        if cur.fetchone():
                            
                            continue

                        session_id = f"SESS_{ev.visitor_id}_{int(ts)}"

                        cur.execute("""
                            INSERT INTO visitor_sessions
                            (
                                session_id,
                                store_id,
                                visitor_id,
                                start_time,
                                is_staff,
                                unauthorized_backroom
                            )
                            VALUES (?,?,?,?,?,?)
                        """, (
                            session_id,
                            ev.store_id,
                            ev.visitor_id,
                            ts,
                            is_staff_int,
                            has_backroom
                        ))


                elif ev.event_type == "EXIT":
                    # Close the most recent open session for this visitor
                    cur.execute("""
                        UPDATE visitor_sessions
                        SET end_time = ?
                        WHERE visitor_id = ? AND store_id = ? AND end_time IS NULL
                    """, (ts, ev.visitor_id, ev.store_id))

                # Mark unauthorized backroom access on existing open session
                if has_backroom:
                    cur.execute("""
                        UPDATE visitor_sessions
                        SET unauthorized_backroom = 1
                        WHERE visitor_id = ? AND store_id = ? AND end_time IS NULL
                    """, (ev.visitor_id, ev.store_id))

            except Exception as e:
                print(f"[Ingestion] Error on event {ev.event_id}: {e}")
                errors += 1

        conn.commit()
        conn.close()
        return success, duplicates, errors
