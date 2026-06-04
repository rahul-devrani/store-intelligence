# Store Intelligence System

Real-time retail analytics from CCTV footage: footfall counting, conversion tracking,
zone dwell analysis, queue monitoring, and anomaly detection.

---

## Stores

| Store ID | Name | Location | Cameras | Coverage Status |
|---|---|---|---|---|
| STORE_BLR_001 | Purplle — Indiranagar | Bengaluru | CAM_1, CAM_2, CAM_3, CAM_5 | ✅ Full (4 cameras validated) |
| STORE_BLR_002 | Purplle — Brigade Road | Bengaluru | CAM_4 | ⚠️ Partial — BOH only (see note) |

> **Store 2 Footage Availability:** Only CAM_4 (Back of House / storeroom) has been validated from
> actual footage. The FOH, Cash Counter, Wall Unit, and Entrance zones are retained as calibrated
> floor-plan reference polygons but are **not** backed by live camera feeds. FOH camera IDs will be
> added once footage is confirmed. No analytics metrics for Store 2 FOH should be treated as live data.

---

### Camera Mapping (Store 1 — Indiranagar)

| Camera ID | Type | Coverage | What you see in footage |
|---|---|---|---|
| CAM_1 | floor | Skincare wall (top-left) | Farmstay, TFS, Minimalist, Aqualogi, Foxtal, JC brand bays. Wide-angle facing south. No tripwire (floor cam). |
| CAM_2 | floor | Cosmetics/Makeup floor (center-right) | L'Oreal, Alps, 6Mars, Swiss Beauty, Lakme, Faces Canada, Maybelline wall; Makeup Unit island. No tripwire (floor cam). |
| CAM_3 | entry | Entrance / glass door | Fisheye top-down view. Purplle branded fascia visible. **Tripwire active** across door threshold. |
| CAM_5 | billing | Cash Counter + ACCESS corner | POS desk with laptop, barcode scanner. Accessories display (teal corner). Staff zone. |

> **Tripwire policy:** Tripwires are only placed on `type=entry` cameras (CAM_3). Floor-plan cameras
> (CAM_1, CAM_2) and billing cameras (CAM_5) do not have tripwires — their zone dwell events are
> used for engagement analytics, not footfall counting.

### Camera Mapping (Store 2 — Brigade Road)

| Camera ID | Type | Coverage | What you see in footage |
|---|---|---|---|
| CAM_4 | backroom | BOH — storeroom | Carton boxes, barrels, makeup artist chair, product shelves. Staff-only zone. |

---

## Conversion Rate

Conversion rate is computed using one of two methods, always indicated by `conversion_method` in the API response:

| `conversion_method` | Description |
|---|---|
| `temporal_overlap` | **Precise.** CCTV billing zone visitor matched to a POS transaction within a 5-minute window. Requires aligned timestamps between CCTV and POS systems. |
| `approximation` | **Approximate.** POS order count divided by CCTV footfall count. Used when temporal alignment is unavailable. May over- or under-count. |
| `unavailable` | No data available — zero footfall or zero POS orders recorded. |

The POS sample file (`pos_transactions.csv`) uses `order_date` / `order_time` fields but does not carry
visitor IDs from CCTV. Until the CCTV pipeline is timestamp-aligned with the POS system,
`approximation` mode is used for Store 1.

---

## Zone Layout Calibration

### Methodology

Polygons were derived directly from the uploaded floor-plan PNGs:

1. **Floor-plan PNG imported** — `store1.png` (1566 × 800 px, landscape) and
   `store2.png` (960 × 1280 px, portrait L-shape).

2. **Landmarks identified** — key fixtures located in each PNG:
   - Store 1: entrance arc (left wall), brand shelf edges (top + bottom wall),
     Makeup Unit island centroid, Cash Counter footprint (right wall, 2000mm offset),
     ACCESS corner (teal box), Fragrance/Nail Unit position.
   - Store 2: entrance double-door (bottom-center, 1917mm wide), FOH area,
     BOH boundary (upper-right L, 7525mm deep), Cash Counter (center, between
     85" LED screen and BOH door), Wall Units 1–18 (left/right/top walls),
     Makeup Unit cluster (right of FOH, 1572 × 1926mm footprint), Gondola 1 & 2.

3. **Pixel coordinates recorded** — corner points of each zone measured in pixels.

4. **Normalised**: `x_norm = x_px / img_width`, `y_norm = y_px / img_height`.

5. **Verified** — polygons visually confirmed against PNG landmarks before
   committing to `data/store_layout.json`.

### Zone Definitions — Store 1 (Indiranagar)

| Zone | Camera | Description |
|---|---|---|
| ENTRANCE | CAM_3 | Glass door threshold — fisheye skewed trapezoid |
| LOBBY | CAM_3 | First ~1.5m inside the store after the door |
| SKINCARE_WALL | CAM_1 | Top wall brand shelves: Salm, TFS, Minimalist, Aqualogi, Foxtal, JC |
| FOH_LEFT | CAM_1 | Left half of main shopping floor |
| FRAGRANCE_NAIL_UNIT | CAM_1 | Fragrance + Nail counter island (center-left floor fixture) |
| COSMETICS_WALL | CAM_2 | Bottom + top wall brand bays: Facia, Mars+Nybae, Mens, Loreal, Beaut / Lakme / Maybelline |
| MAKEUP_UNIT | CAM_2 | Dual chair makeup island (900mm × 900mm per plan) |
| FOH_RIGHT | CAM_2 | Right half of main shopping floor |
| BILLING | CAM_5 | POS desk — funnel stage 3 anchor zone |
| CASH_COUNTER | CAM_5 | Alias of BILLING used for display |
| ACCESS_CORNER | CAM_5 | Accessories / impulse-buy corner (teal box on plan) |
| BACKROOM | CAM_5 | Narrow staff-only corridor behind Cash Counter |

### Zone Definitions — Store 2 (Brigade Road)

Floor-plan reference zones (calibrated from PNG, awaiting matched camera footage):

| Zone | Description | Live Camera? |
|---|---|---|
| ENTRANCE | Bottom-center double-door (1917mm wide) | ❌ TBD |
| FOH | Main shopping floor (gondolas, makeup units, open walking) | ❌ TBD |
| BOH | Upper-right L-shape back room (7525mm deep, 4850mm wide) | ✅ CAM_4 |
| CASH_COUNTER | Center between BOH door and 85" LED screen | ❌ TBD |
| LEFT_WALL_UNITS | Wall Units 1–6 (pink zone, left wall) | ❌ TBD |
| RIGHT_WALL_UNITS | Wall Units 13–18 (pink zone, right wall) | ❌ TBD |
| TOP_WALL_UNITS | Wall Units 7–12 (top of FOH) | ❌ TBD |
| MAKEUP_UNIT | 4-table makeup cluster (right of FOH) | ❌ TBD |
| GONDOLA_ZONE | Diagonal gondola fixtures (center-left of FOH) | ❌ TBD |

---

## Architecture

```
CCTV clips (CAM_1 .. CAM_5)
    │
    ▼
pipeline/detect.py        YOLOv8n + ByteTrack per-frame detection
pipeline/tracker.py       Same-camera track repair + cross-camera Re-ID
    │  (HTTP POST batches)
    ▼
POST /events/ingest       FastAPI ingestion endpoint
app/ingestion.py          Deduplication, session management, SQLite write
    │
    ▼
SQLite (WAL mode)         raw_events, visitor_sessions, visitors, heatmap_bins
    │
    ▼
GET /stores/{id}/metrics   Real-time analytics (with conversion_method field)
GET /stores/{id}/funnel
GET /stores/{id}/heatmap
GET /stores/{id}/anomalies
GET /stores/{id}/layout    zone polygons + tripwires (entry cameras only)
GET /stores              lists all registered stores
```

---

## Setup in 5 Commands

```bash
# 1. Build and start API
git clone <repo-url> store-intelligence && cd store-intelligence
docker compose up -d --build

# 2. Verify health
curl -s http://localhost:8000/health | python3 -m json.tool
# Look for store_feed_status → feed_lag_seconds + stale_feed per store

# 3. Place clips and run detection
# Clips must be: data/clips/<STORE_ID>/<CAM_ID>/<clip>.mp4
# e.g. data/clips/STORE_BLR_001/CAM_1/floor.mp4
#      data/clips/STORE_BLR_001/CAM_5/billing.mp4
docker compose exec api bash ./pipeline/run.sh

# 4. Query analytics
curl -s http://localhost:8000/stores/STORE_BLR_001/metrics | python3 -m json.tool
curl -s http://localhost:8000/stores/STORE_BLR_001/layout  | python3 -m json.tool

# 5. Run tests
docker compose exec api python3 -m pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## Live Dashboard

```bash
pip install streamlit Pillow matplotlib
streamlit run dashboard.py
```

Dashboard tabs:
- **Funnel** — 4-stage conversion with drop-off %
- **Heatmap** — spatial density rendered on top of floor-plan PNG
- **Zone Layout** — all polygons + tripwires overlaid on floor plan
- **Zone Dwell** — per-zone average dwell bar chart
- **Anomalies** — CRITICAL / WARN / INFO with suggested actions
- **Diagnostics** — event density, fragmentation, totals

Place `store1.png` and `store2.png` in the `data/` folder for the overlay to render.
Without the PNGs the dashboard falls back to an SVG normalised-coordinate viewer.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET  | `/health` | Service health + per-store feed lag + stale feed status |
| GET  | `/stores` | List all registered stores and cameras |
| POST | `/events/ingest` | Batch ingest up to 500 events (idempotent) |
| POST | `/events/heatmap` | Ingest spatial heatmap coordinates |
| GET  | `/stores/{id}/metrics` | Footfall, conversion (with `conversion_method`), dwell, queue depth |
| GET  | `/stores/{id}/funnel` | 4-stage conversion funnel with drop-off % |
| GET  | `/stores/{id}/heatmap` | 10×10 normalised spatial density grid |
| GET  | `/stores/{id}/anomalies` | Active anomalies with severity |
| GET  | `/stores/{id}/layout` | Zone polygons + tripwires (entry cams only) |

### Health Response Fields

```json
{
  "status": "healthy",
  "datastore_reachable": true,
  "total_events_stored": 1234,
  "store_feed_status": {
    "STORE_BLR_001": {
      "latest_event_timestamp": 1748970123.4,
      "feed_lag_seconds": 42,
      "stale_feed": false
    },
    "STORE_BLR_002": {
      "latest_event_timestamp": null,
      "feed_lag_seconds": null,
      "stale_feed": true
    }
  }
}
```

### Metrics `pos_analytics` Fields

```json
{
  "conversion_rate_percentage": 14.3,
  "conversion_method": "approximation",
  "conversion_note": "POS order count divided by CCTV footfall. Temporal alignment unavailable.",
  "orders_count_today": 12,
  "net_revenue_inr_today": 8432.50
}
```

---

## Docs

- `docs/DESIGN.md` — architecture walkthrough and AI-assisted decision log
- `docs/CHOICES.md` — model selection, schema design, storage rationale
- `data/store_layout.json` — zone polygons with full calibration notes
