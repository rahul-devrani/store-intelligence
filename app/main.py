from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import List

from fastapi import Body, FastAPI, HTTPException, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import database
from app.anomalies import AnomalyDetector
from app.config import StoreConfigManager
from app.funnel import FunnelCalculator
from app.health import HealthChecker
from app.ingestion import IngestionManager
from app.metrics import MetricsCalculator
from app.models import EventPayload, HeatmapBatchPayload

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("StoreIntelligenceAPI")

app = FastAPI(
    title="Store Intelligence API",
    description="Real-time retail analytics from CCTV event streams.",
    version="2.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

config_manager = StoreConfigManager()

#  Floor plan PNG validation on startup 
_PNG_PATHS = ["data/store1.png", "store1.png", "data/store2.png", "store2.png"]

@app.on_event("startup")
def on_startup():
    database.init_db()
    # if floor-plan PNGs are missing
    for store_id in config_manager.all_store_ids():
        store = config_manager.get_store(store_id)
        if not store or not store.floor_plan_png:
            continue
        png = store.floor_plan_png
        candidates = [f"data/{png}", png]
        found = any(os.path.exists(p) for p in candidates)
        if not found:
            logger.warning(
                json.dumps({
                    "event": "PNG_MISSING",
                    "store_id": store_id,
                    "floor_plan_png": png,
                    "message": f"Floor-plan PNG '{png}' not found — dashboard will use SVG fallback. "
                               "Place PNG in data/ to enable overlay rendering.",
                })
            )


# Structured logging middleware 
@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
    start = time.time()
    parts = request.url.path.split("/")
    store_id = parts[2] if len(parts) > 2 and parts[1] == "stores" else "GLOBAL"
    response = await call_next(request)
    latency_ms = int((time.time() - start) * 1000)
    log = {
        "trace_id": trace_id,
        "store_id": store_id,
        "endpoint": request.url.path,
        "method": request.method,
        "latency_ms": latency_ms,
        "status_code": response.status_code,
    }
    logger.info(json.dumps(log))
    return response


# DB safeguard middleware 
@app.middleware("http")
async def db_safeguard_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        return JSONResponse(
            status_code=503,
            content={"detail": "Service temporarily unavailable.", "error_code": "INTERNAL_ERROR"},
        )


# Endpoints 

@app.get("/health", tags=["ops"])
def health():
    """
    Service health check.
    Returns feed lag per store, stale feed status, and datastore reachability.
    """
    result = HealthChecker.audit_health()

    # Augment with per-store feed lag
    store_feed_status = {}
    now_ts = time.time()
    conn = database.get_db_connection()
    cur = conn.cursor()
    for sid in config_manager.all_store_ids():
        try:
            cur.execute(
                "SELECT MAX(timestamp) as latest FROM raw_events WHERE store_id = ?", (sid,)
            )
            row = cur.fetchone()
            latest_ts = row["latest"] if row and row["latest"] else None
            if latest_ts is not None:
                lag = int(now_ts - latest_ts)
                stale = lag > 600  
            else:
                lag = None
                stale = True  # no events == stale
            store_feed_status[sid] = {
                "latest_event_timestamp": latest_ts,
                "feed_lag_seconds": lag,
                "stale_feed": stale,
            }
        except Exception:
            store_feed_status[sid] = {"latest_event_timestamp": None, "feed_lag_seconds": None, "stale_feed": True}
    conn.close()

    result["store_feed_status"] = store_feed_status

    if not result["datastore_reachable"]:
        return JSONResponse(status_code=503, content=result)
    return result


@app.post("/events/ingest", tags=["ingest"])
def ingest_events(events: List[EventPayload] = Body(...)):
    """
    Idempotently ingest up to 500 tracking events.
    camera_id must match the physical camera label (CAM_1 .. CAM_5).
    """
    if not events:
        raise HTTPException(status_code=400, detail="Empty event batch.")
    if len(events) > 500:
        raise HTTPException(status_code=400, detail="Batch size limit is 500 events.")

    success, duplicates, errors = IngestionManager.process_batch(events)

    status = "success"
    if errors > 0 and success == 0:
        status = "failed"
    elif errors > 0:
        status = "partial_success"

    return JSONResponse(
        content={
            "status": status,
            "processed": success,
            "duplicates_skipped": duplicates,
            "malformed_skipped": errors,
        },
        headers={"X-Event-Count": str(len(events))},
    )


@app.post("/events/heatmap", tags=["ingest"])
def ingest_heatmap(batch: HeatmapBatchPayload = Body(...)):
    """Update spatial density heatmap grid."""
    conn = database.get_db_connection()
    cur = conn.cursor()
    for cell in batch.bins:
        cur.execute("""
            INSERT INTO heatmap_bins (store_id, x_grid, y_grid, frequency_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(store_id, x_grid, y_grid) DO UPDATE SET
                frequency_count = frequency_count + excluded.frequency_count
        """, (batch.store_id, cell.x_grid, cell.y_grid, cell.frequency))
    conn.commit()
    conn.close()
    return {"status": "success", "bins_updated": len(batch.bins)}


@app.get("/stores/{id}/metrics", tags=["analytics"])
def get_metrics(id: str = Path(..., description="Store ID e.g. STORE_BLR_001")):
    if not config_manager.get_store(id):
        raise HTTPException(status_code=404, detail=f"Store '{id}' not registered.")
    return MetricsCalculator.calculate_store_metrics(id)


@app.get("/stores/{id}/funnel", tags=["analytics"])
def get_funnel(id: str = Path(...)):
    if not config_manager.get_store(id):
        raise HTTPException(status_code=404, detail=f"Store '{id}' not registered.")
    return FunnelCalculator.calculate_funnel(id)


@app.get("/stores/{id}/heatmap", tags=["analytics"])
def get_heatmap(id: str = Path(...)):
    if not config_manager.get_store(id):
        raise HTTPException(status_code=404, detail=f"Store '{id}' not registered.")

    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT x_grid, y_grid, frequency_count FROM heatmap_bins WHERE store_id = ?", (id,)
    )
    rows = cur.fetchall()
    conn.close()

    grid = [[0] * 10 for _ in range(10)]
    max_val = 0
    for r in rows:
        grid[r["y_grid"]][r["x_grid"]] = r["frequency_count"]
        max_val = max(max_val, r["frequency_count"])

    norm_grid = [
        [round((v / max_val) * 100) if max_val > 0 else 0 for v in row]
        for row in grid
    ]

    data_confidence = "LOW" if sum(sum(r) for r in grid) < 20 else "OK"

    return {
        "store_id": id,
        "grid_resolution": "10x10",
        "spatial_matrix": norm_grid,
        "raw_matrix": grid,
        "data_confidence": data_confidence,
    }


@app.get("/stores/{id}/anomalies", tags=["analytics"])
def get_anomalies(id: str = Path(...)):
    if not config_manager.get_store(id):
        raise HTTPException(status_code=404, detail=f"Store '{id}' not registered.")
    return AnomalyDetector.detect_anomalies(id)


@app.get("/stores/{id}/layout", tags=["analytics"])
def get_layout(id: str = Path(..., description="Store ID e.g. STORE_BLR_001")):
    """
    Return all zone polygons, tripwires, and camera descriptions for a store.
    Polygon coordinates are normalised to [0, 1] relative to the floor-plan PNG.
    Use the floor_plan_png field to match against the correct image file.
    """
    layout = config_manager.get_layout_response(id)
    if not layout:
        raise HTTPException(status_code=404, detail=f"Store '{id}' not registered.")
    return layout


@app.get("/stores", tags=["ops"])
def list_stores():
    """List all registered store IDs and names."""
    out = []
    for sid in config_manager.all_store_ids():
        store = config_manager.get_store(sid)
        out.append({
            "store_id": sid,
            "name": store.name if store else sid,
            "cameras": list(store.cameras.keys()) if store else [],
        })
    return {"stores": out}
