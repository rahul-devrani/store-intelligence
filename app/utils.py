"""
app/utils.py — Shared utilities for the Store Intelligence API.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, List, Optional


# Timestamp helpers 

def iso_to_seconds(ts: str) -> Optional[float]:
    """
    Parse an ISO-8601 UTC timestamp string → seconds-since-midnight float.
    Returns None if parsing fails.

    Examples:
        "2026-03-03T14:22:10Z" → 51730.0
        "2026-03-03T00:00:00Z" → 0.0
    """
    try:
        time_part = ts.split("T")[-1].replace("Z", "").split(".")[0]
        h, m, s = map(int, time_part.split(":"))
        return float(h * 3600 + m * 60 + s)
    except Exception:
        return None


def seconds_to_iso(seconds: float, date_str: str = "2026-03-03") -> str:
    """
    Convert seconds-since-midnight back to an ISO-8601 UTC string.
    Uses date_str as the date component (defaults to challenge date).
    """
    h = int(seconds // 3600) % 24
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{date_str}T{h:02d}:{m:02d}:{s:02d}Z"


def now_epoch_seconds() -> float:
    """Return current UTC time as seconds-since-midnight for today."""
    now = datetime.datetime.utcnow()
    return float(now.hour * 3600 + now.minute * 60 + now.second)


def today_midnight_epoch() -> float:
    """Return today's UTC midnight as a Unix epoch timestamp."""
    return datetime.datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()


# Schema helpers 

def new_event_id() -> str:
    """Generate a UUID-v4 event ID string."""
    return str(uuid.uuid4())


def validate_event_schema(event: Dict[str, Any]) -> List[str]:
    """
    Validate an event dict against the required schema.
    Returns a list of error strings (empty list means valid).
    """
    errors = []
    required = ["event_id", "store_id", "camera_id", "visitor_id",
                "event_type", "timestamp", "metadata"]
    for field in required:
        if field not in event:
            errors.append(f"Missing required field: '{field}'")

    valid_event_types = {
        "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
        "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY",
    }
    et = event.get("event_type", "")
    if et and et not in valid_event_types:
        errors.append(f"Unknown event_type: '{et}'")

    conf = event.get("confidence")
    if conf is not None and not (0.0 <= float(conf) <= 1.0):
        errors.append(f"confidence must be in [0.0, 1.0], got {conf}")

    ts = event.get("timestamp", "")
    if ts and iso_to_seconds(ts) is None:
        errors.append(f"Cannot parse timestamp: '{ts}'")

    return errors


# Pagination helper 

def paginate(items: List[Any], page: int = 1, page_size: int = 50) -> Dict[str, Any]:
    """Simple list paginator. page is 1-indexed."""
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": items[start:end],
    }


# Safe division 

def safe_pct(numerator: Optional[int], denominator: Optional[int]) -> Optional[float]:
    """Return (numerator / denominator * 100) rounded to 1dp, or None if undefined."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round((numerator / denominator) * 100, 1)
