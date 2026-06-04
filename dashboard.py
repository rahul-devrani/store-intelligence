"""
Store Intelligence Dashboard  v3.0
Clean, light-themed analytics dashboard simple and easy to understand.

Run:  streamlit run dashboard.py
"""

from __future__ import annotations

import io
import time
from typing import Any, Dict, List, Optional

import numpy as np
import requests
import streamlit as st

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

API_BASE = "http://localhost:8000"
REFRESH_INTERVAL = 5  # seconds

STORES = ["STORE_BLR_001", "STORE_BLR_002"]
STORE_META = {
    "STORE_BLR_001": {
        "name": "Purplle Indiranagar",
        "cameras": ["CAM_1", "CAM_2", "CAM_3", "CAM_5"],
        "cam_labels": {
            "CAM_1": "Skincare Wall (TFS/Minimalist/Aqualogi)",
            "CAM_2": "Cosmetics Floor (Lakme/Maybelline/LOreal)",
            "CAM_3": "Entrance / Glass Door",
            "CAM_5": "Cash Counter / Billing",
        },
        "png": "store1.png",
    },
  "STORE_BLR_002": {
        "name": "Purplle Brigade Road",
        "cameras": ["CAM_1", "CAM_2", "CAM_3", "CAM_4"],  # include all 4 cams
        "cam_labels": {
            "CAM_1": "Entry Camera 1",
            "CAM_2": "Entry Camera 2",
            "CAM_3": "Zone Floor",
            "CAM_4": "Billing Area",
        },
        "png": "store2.png",
    },
}

ZONE_COLOURS = {
    "ENTRANCE":            (0,   200, 80,  120),
    "LOBBY":               (0,   220, 120, 100),
    "FOH_LEFT":            (30,  144, 255, 80),
    "FOH_RIGHT":           (30,  144, 255, 80),
    "SKINCARE_WALL":       (50,  205, 50,  130),
    "COSMETICS_WALL":      (255, 105, 180, 130),
    "MAKEUP_UNIT":         (255, 165, 0,   140),
    "FRAGRANCE_NAIL_UNIT": (148, 0,   211, 130),
    "CASH_COUNTER":        (220, 20,  60,  130),
    "BILLING":             (220, 20,  60,  130),
    "ACCESS_CORNER":       (0,   206, 209, 130),
    "BOH":                 (169, 169, 169, 130),
    "BACKROOM":            (105, 105, 105, 130),
    "FOH":                 (30,  144, 255, 80),
    "LEFT_WALL_UNITS":     (60,  179, 113, 130),
    "RIGHT_WALL_UNITS":    (60,  179, 113, 130),
    "TOP_WALL_UNITS":      (60,  179, 113, 130),
    "GONDOLA_ZONE":        (210, 180, 140, 130),
}
DEFAULT_ZONE_COLOUR = (100, 100, 200, 110)

# Page config + custom CSS
st.set_page_config(
    page_title="Store Intelligence",
    page_icon="Store",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* Global background & font */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #F8F7F4 !important;
    font-family: 'Segoe UI', sans-serif;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #FFFFFF !important;
    border-right: 1px solid #E8E5E0;
}
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span {
    color: #3D3D3D !important;
}

/* Main content area padding */
.main .block-container {
    padding-top: 1.5rem;
    padding-left: 2rem;
    padding-right: 2rem;
    max-width: 1400px;
}

/* KPI card tiles */
.kpi-row {
    display: flex;
    gap: 14px;
    margin-bottom: 1.5rem;
}
.kpi-card {
    flex: 1;
    background: #FFFFFF;
    border: 1px solid #E8E5E0;
    border-radius: 12px;
    padding: 16px 20px;
    min-width: 0;
}
.kpi-label {
    font-size: 12px;
    color: #888;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
}
.kpi-value {
    font-size: 26px;
    font-weight: 700;
    color: #1A1A1A;
    line-height: 1.1;
}
.kpi-icon {
    font-size: 18px;
    margin-bottom: 8px;
    display: block;
}

/* Camera pill badges */
.cam-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #F0EEF9;
    color: #5B4DA0;
    border-radius: 20px;
    padding: 5px 12px;
    font-size: 13px;
    font-weight: 500;
    margin: 4px 4px 4px 0;
}
.cam-pill-label {
    color: #6B6B6B;
    font-size: 12px;
    margin-top: 2px;
}

/* Zone badge chips */
.zone-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    color: white;
    margin: 3px 3px 3px 0;
}

/* Status dots */
.dot-green { color: #2ECC71; }
.dot-red   { color: #E74C3C; }
.dot-orange{ color: #F39C12; }

/* Anomaly cards */
.anomaly-card {
    background: #FFFFFF;
    border-radius: 10px;
    border-left: 4px solid #ccc;
    padding: 14px 18px;
    margin-bottom: 12px;
}
.anomaly-critical { border-left-color: #E74C3C; }
.anomaly-warn     { border-left-color: #F39C12; }
.anomaly-info     { border-left-color: #3498DB; }
.anomaly-title    { font-weight: 600; font-size: 14px; color: #1A1A1A; margin-bottom: 4px; }
.anomaly-detail   { font-size: 13px; color: #555; margin-bottom: 4px; }
.anomaly-action   { font-size: 12px; color: #888; }

/* Tab styling */
[data-testid="stTabs"] [role="tab"] {
    font-size: 13px;
    font-weight: 500;
    color: #666;
    padding: 8px 18px;
    border-radius: 6px 6px 0 0;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #5B4DA0;
    background: #F0EEF9;
}

/* Section headers */
.section-header {
    font-size: 15px;
    font-weight: 600;
    color: #2C2C2C;
    margin: 0 0 12px 0;
    padding-bottom: 6px;
    border-bottom: 2px solid #EAE8F0;
}

/* Metric stat boxes (diagnostics) */
.stat-box {
    background: #FFFFFF;
    border: 1px solid #E8E5E0;
    border-radius: 10px;
    padding: 14px 18px;
    text-align: center;
}
.stat-box-value {
    font-size: 22px;
    font-weight: 700;
    color: #1A1A1A;
}
.stat-box-label {
    font-size: 12px;
    color: #999;
    margin-top: 4px;
}

/* Metric component overrides (st.metric) */
[data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid #E8E5E0 !important;
    border-radius: 12px !important;
    padding: 14px 18px !important;
}
[data-testid="stMetricLabel"] {
    font-size: 12px !important;
    color: #888 !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.4px !important;
}
[data-testid="stMetricValue"] {
    font-size: 24px !important;
    font-weight: 700 !important;
    color: #1A1A1A !important;
}

/* Page title */
h1 {
    font-size: 22px !important;
    font-weight: 700 !important;
    color: #1A1A1A !important;
}
h2 {
    font-size: 16px !important;
    font-weight: 600 !important;
    color: #2C2C2C !important;
}
h3 {
    font-size: 14px !important;
    font-weight: 600 !important;
    color: #3D3D3D !important;
}

/* Dividers */
hr {
    border: none;
    border-top: 1px solid #E8E5E0;
    margin: 1rem 0;
}

/* Alert colours */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    font-size: 14px !important;
}

/* Toggle / checkbox */
[data-testid="stToggle"] label {
    font-size: 13px !important;
    color: #3D3D3D !important;
}

/* Expander */
[data-testid="stExpander"] {
    background: #FAFAFA !important;
    border: 1px solid #E8E5E0 !important;
    border-radius: 8px !important;
}
</style>
""", unsafe_allow_html=True)


# Sidebar
with st.sidebar:
    st.markdown("## Store Intelligence")
    st.markdown("***")
    selected_store = st.selectbox(
        "Choose Store",
        STORES,
        format_func=lambda s: STORE_META[s]["name"],
    )
    st.markdown("***")
    auto_refresh = st.toggle("Auto refresh every 5s", value=True)
    st.markdown("***")
    st.caption(f"API endpoint\n`{API_BASE}`")
    health_ph = st.empty()


# Data fetchers
@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch(endpoint: str) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(f"{API_BASE}{endpoint}", timeout=4)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"_error": str(e)}


def get_metrics(sid):   return fetch(f"/stores/{sid}/metrics")
def get_funnel(sid):    return fetch(f"/stores/{sid}/funnel")
def get_heatmap(sid):   return fetch(f"/stores/{sid}/heatmap")
def get_anomalies(sid): return fetch(f"/stores/{sid}/anomalies")
def get_layout(sid):    return fetch(f"/stores/{sid}/layout")
def get_health():       return fetch("/health")


# Health badge
def render_health():
    h = get_health()
    if h and not h.get("_error"):
        status = h.get("status", "unknown")
        is_ok = status == "healthy"
        dot = "OK" if is_ok else "DOWN"
        events = h.get("total_events_stored", 0)
        health_ph.markdown(
            f"**API:** `{status}` ({dot})  \n"
            f"<small style='color:#888'>Events stored: {events:,}</small>",
            unsafe_allow_html=True,
        )
    else:
        health_ph.markdown("**API:** `unreachable`")


# Anomaly banner
def render_anomaly_banner(sid):
    data = get_anomalies(sid)
    if not data or data.get("_error"):
        return
    sev = data.get("severity_index", "NORMAL")
    count = data.get("anomaly_count", 0)
    if sev == "CRITICAL":
        st.error(f"Critical alert {count} active issue(s). Check the Anomalies tab.")
    elif sev == "WARN":
        st.warning(f"{count} warning(s) detected. See the Anomalies tab for details.")
    else:
        st.success("All clear. No anomalies detected.")


# KPI cards
def render_kpis(metrics):
    va = metrics.get("video_analytics", {})
    pa = metrics.get("pos_analytics", {})

    footfall   = va.get("footfall_count", 0)
    checkout   = va.get("checkout_visitors", 0)
    cr         = pa.get("conversion_rate_percentage")
    orders     = pa.get("orders_count_today", 0)
    revenue    = pa.get("net_revenue_inr_today", 0)

    cols = st.columns(5)
    kpis = [
        ("Footfall Today",  f"{footfall:,}"),
        ("At Checkout",     str(checkout)),
        ("Conversion Rate", f"{cr}%" if cr is not None else "N/A"),
        ("Orders Today",    str(orders)),
        ("Revenue Today",   f"Rs {revenue:,.0f}"),
    ]
    for col, (label, value) in zip(cols, kpis):
        with col:
            st.markdown(
                f"""<div class="kpi-card">
                    <div class="kpi-label">{label}</div>
                    <div class="kpi-value">{value}</div>
                </div>""",
                unsafe_allow_html=True,
            )


# Camera panel
def render_camera_panel(sid):
    meta = STORE_META[sid]
    st.markdown(
        f"<p class='section-header'>Cameras {meta['name']}</p>",
        unsafe_allow_html=True,
    )
    html = ""
    for cam_id in meta["cameras"]:
        label = meta["cam_labels"].get(cam_id, cam_id)
        html += (
            f"<span class='cam-pill'>{cam_id}</span>"
            f"<span class='cam-pill-label'>{label}</span>&nbsp;&nbsp;"
        )
    st.markdown(html, unsafe_allow_html=True)


def render_live_cameras(sid):
    st.markdown("### Live Camera Feeds")

    cams = STORE_META[sid]["cameras"]

    cols = st.columns(2)

    for i, cam_id in enumerate(cams):

        video_map = {
            ("STORE_BLR_001", "CAM_1"): "data/clips/STORE_BLR_001/CAM_1/CAM 1 - zone.mp4",
            ("STORE_BLR_001", "CAM_2"): "data/clips/STORE_BLR_001/CAM_2/CAM 2 - zone.mp4",
            ("STORE_BLR_001", "CAM_3"): "data/clips/STORE_BLR_001/CAM_3/CAM 3 - entry.mp4",
            ("STORE_BLR_001", "CAM_5"): "data/clips/STORE_BLR_001/CAM_5/CAM 5 - billing.mp4",

            ("STORE_BLR_002", "CAM_1"): "data/clips/STORE_BLR_002/CAM_1/entry1.mp4",
            ("STORE_BLR_002", "CAM_2"): "data/clips/STORE_BLR_002/CAM_2/entry2.mp4",
            ("STORE_BLR_002", "CAM_3"): "data/clips/STORE_BLR_002/CAM_3/zone.mp4",
            ("STORE_BLR_002", "CAM_4"): "data/clips/STORE_BLR_002/CAM_4/billing_area.mp4",
        }

        path = video_map.get((sid, cam_id))

        with cols[i % 2]:
            st.markdown(f"**{cam_id}**")

            try:
                st.video(path)
            except:
                st.warning(f"Video not found for {cam_id}")


# Funnel
def render_funnel(sid):
    import pandas as pd
    data = get_funnel(sid)
    if not data or data.get("_error"):
        st.info("Funnel data is not available right now.")
        return

    f = data.get("funnel", {})
    stages = {
        "Entered Store":      f.get("stage_1_entered", 0),
        "Browsed Aisles":     f.get("stage_2_browsed_aisles", 0),
        "Reached Checkout":   f.get("stage_3_reached_checkout", 0),
        "Completed Purchase": f.get("stage_4_completed_purchase") or 0,
    }

    st.markdown("<p class='section-header'>Visitor Journey</p>", unsafe_allow_html=True)
    df = pd.DataFrame({"Stage": list(stages.keys()), "Visitors": list(stages.values())})
    st.bar_chart(df.set_index("Stage"), color="#7C6BC9", height=280)

    drop = data.get("drop_off_pct", {})
    st.markdown("<p class='section-header' style='margin-top:1rem'>Drop off at Each Step</p>", unsafe_allow_html=True)
    cols = st.columns(3)
    for col, (lbl, val) in zip(cols, [
        ("Entry to Browse",      drop.get("entry_to_browse")),
        ("Browse to Checkout",   drop.get("browse_to_checkout")),
        ("Checkout to Purchase", drop.get("checkout_to_purchase")),
    ]):
        with col:
            st.metric(lbl, f"{val}%" if val is not None else "N/A")


# Heatmap
def _draw_heatmap_overlay(base_img, matrix):
    W, H = base_img.size
    cell_w, cell_h = W / 10, H / 10
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for row_i, row in enumerate(matrix):
        for col_i, val in enumerate(row):
            if val == 0:
                continue
            ratio = val / 100.0
            r = int(min(255, ratio * 2 * 255))
            g = int(min(255, (1 - ratio) * 2 * 255))
            alpha = int(40 + ratio * 160)
            x0, y0 = int(col_i * cell_w), int(row_i * cell_h)
            x1, y1 = int((col_i + 1) * cell_w), int((row_i + 1) * cell_h)
            draw.rectangle([x0, y0, x1, y1], fill=(r, g, alpha, alpha))
    return Image.alpha_composite(base_img.convert("RGBA"), overlay).convert("RGB")


def render_heatmap_tab(sid: str):
    heatmap_data = get_heatmap(sid)
    if not heatmap_data or heatmap_data.get("_error"):
        st.info("Heatmap data is not available right now.")
        return

    confidence = heatmap_data.get("data_confidence", "LOW")
    if confidence == "LOW":
        st.info("Limited data collected so far. Heatmap accuracy is low.")

    matrix = heatmap_data.get("spatial_matrix", [[0] * 10 for _ in range(10)])
    arr = np.array(matrix)

    png_name = STORE_META[sid]["png"]
    base_img = None
    if PIL_OK:
        for path in [f"data/{png_name}", png_name]:
            try:
                base_img = Image.open(path)
                break
            except Exception:
                pass

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("<p class='section-header'>Density Map</p>", unsafe_allow_html=True)
        if PIL_OK and base_img:
            composited = _draw_heatmap_overlay(base_img, matrix)
            st.image(composited, caption=f"Occupancy density {STORE_META[sid]['name']}", use_column_width=True)
        else:
            import matplotlib.pyplot as plt
            import matplotlib.colors as mcolors
            fig, ax = plt.subplots(figsize=(8, 5))
            cmap = mcolors.LinearSegmentedColormap.from_list(
                "heatmap", ["#EAF3DE", "#97C459", "#F39C12", "#E74C3C"]
            )
            im = ax.imshow(arr, cmap=cmap, vmin=0, vmax=100, aspect="auto")
            ax.set_title(f"Occupancy density {STORE_META[sid]['name']}", fontsize=12, color="#2C2C2C")
            ax.set_xlabel("X grid"); ax.set_ylabel("Y grid")
            plt.colorbar(im, ax=ax, label="Occupancy %")
            fig.patch.set_facecolor("#F8F7F4")
            ax.set_facecolor("#FAFAFA")
            st.pyplot(fig)
            plt.close(fig)

    with col2:
        st.markdown("<p class='section-header'>Summary</p>", unsafe_allow_html=True)
        hottest = np.unravel_index(np.argmax(arr), arr.shape)
        st.metric("Hottest Cell",  f"X{hottest[1]}, Y{hottest[0]}")
        st.metric("Peak Density",  f"{arr[hottest]:.0f}%")
        st.metric("Avg Density",   f"{arr.mean():.1f}%")
        st.metric("Active Cells",  f"{np.count_nonzero(arr)} / 100")
        st.markdown("***")
        st.markdown(
            "<small style='color:#888'>Low &nbsp; Medium &nbsp; High</small>",
            unsafe_allow_html=True,
        )


# Zone layout
def _draw_zone_polygons(base_img, layout):
    W, H = base_img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def norm_to_px(pts):
        return [(int(x * W), int(y * H)) for x, y in pts]

    for cam_id, cam_data in layout.get("cameras", {}).items():
        for zone_id, zone_data in cam_data.get("zones", {}).items():
            poly = zone_data.get("polygon", [])
            if len(poly) < 3:
                continue
            colour = ZONE_COLOURS.get(zone_id, DEFAULT_ZONE_COLOUR)
            px_poly = norm_to_px(poly)
            draw.polygon(px_poly, fill=colour)
            draw.polygon(px_poly, outline=(colour[0], colour[1], colour[2], 220), width=2)
            cx = int(sum(p[0] for p in px_poly) / len(px_poly))
            cy = int(sum(p[1] for p in px_poly) / len(px_poly))
            draw.text((cx, cy), zone_id.replace("_", "\n"), fill=(255, 255, 255, 230))
        tw = cam_data.get("tripwire")
        if tw:
            pts = tw.get("line", [])
            if len(pts) == 2:
                px_pts = norm_to_px(pts)
                draw.line([px_pts[0], px_pts[1]], fill=(255, 0, 0, 220), width=3)

    for zone_id, zone_data in layout.get("floor_plan_reference_zones", {}).items():
        poly = zone_data.get("polygon", [])
        if len(poly) < 3:
            continue
        colour = ZONE_COLOURS.get(zone_id, DEFAULT_ZONE_COLOUR)
        px_poly = norm_to_px(poly)
        draw.polygon(px_poly, outline=(colour[0], colour[1], colour[2], 180), width=2)

    return Image.alpha_composite(base_img.convert("RGBA"), overlay).convert("RGB")


def _render_svg_layout(layout):
    W, H = 600, 360
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'style="background:#F0EEF9;border-radius:10px;border:1px solid #DDD">'
    ]
    svg.append('<text x="12" y="22" fill="#888" font-size="11" font-family="Segoe UI">'
               'Zone layout (no floor plan PNG found)</text>')

    for cam_id, cam_data in layout.get("cameras", {}).items():
        for zone_id, zone_data in cam_data.get("zones", {}).items():
            poly = zone_data.get("polygon", [])
            if len(poly) < 3:
                continue
            colour = ZONE_COLOURS.get(zone_id, DEFAULT_ZONE_COLOUR)
            pts_str = " ".join(f"{x*W:.0f},{y*H:.0f}" for x, y in poly)
            hex_fill = "#{:02x}{:02x}{:02x}".format(*colour[:3])
            cx = sum(x for x, y in poly) / len(poly) * W
            cy = sum(y for x, y in poly) / len(poly) * H
            svg.append(
                f'<polygon points="{pts_str}" fill="{hex_fill}" fill-opacity="0.45" '
                f'stroke="{hex_fill}" stroke-width="1.5"/>'
            )
            svg.append(
                f'<text x="{cx:.0f}" y="{cy:.0f}" fill="#2C2C2C" font-size="9" '
                f'font-family="Segoe UI" text-anchor="middle">{zone_id}</text>'
            )
        tw = cam_data.get("tripwire")
        if tw:
            line = tw.get("line", [])
            if len(line) == 2:
                x1, y1 = line[0][0] * W, line[0][1] * H
                x2, y2 = line[1][0] * W, line[1][1] * H
                svg.append(
                    f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                    f'stroke="#E74C3C" stroke-width="2" stroke-dasharray="6,3"/>'
                )
    svg.append("</svg>")
    st.markdown("\n".join(svg), unsafe_allow_html=True)


def render_layout_tab(sid: str):
    layout = get_layout(sid)
    if not layout or layout.get("_error"):
        st.info(f"Layout data unavailable: {layout.get('_error', 'API unreachable') if layout else 'API unreachable'}")
        return

    st.markdown(
        f"<p class='section-header'>{layout.get('store_name', '')} Floor Plan</p>",
        unsafe_allow_html=True,
    )
    if layout.get("calibration_note"):
        st.caption(layout["calibration_note"])

    png_name = layout.get("floor_plan_png", "")
    base_img = None
    if PIL_OK:
        for path in [f"data/{png_name}", png_name]:
            try:
                base_img = Image.open(path)
                break
            except Exception:
                pass

    col1, col2 = st.columns([3, 1])
    with col1:
        if PIL_OK and base_img:
            annotated = _draw_zone_polygons(base_img, layout)
            st.image(annotated, caption="Zone polygons on floor plan", use_column_width=True)
            st.caption("Red dashed lines are tripwires (entry count triggers)")
        else:
            _render_svg_layout(layout)

    with col2:
        st.markdown("<p class='section-header'>Camera Zones</p>", unsafe_allow_html=True)
        for cam_id, cam_data in layout.get("cameras", {}).items():
            cam_label = STORE_META[sid]["cam_labels"].get(cam_id, cam_id)
            with st.expander(f"{cam_id} {cam_label}", expanded=False):
                st.caption(cam_data.get("description", ""))
                for zone_id, zone_data in cam_data.get("zones", {}).items():
                    colour = ZONE_COLOURS.get(zone_id, DEFAULT_ZONE_COLOUR)
                    hex_c = "#{:02x}{:02x}{:02x}".format(*colour[:3])
                    st.markdown(
                        f"<span class='zone-badge' style='background:{hex_c}'>{zone_id}</span> "
                        f"<small style='color:#666'>{zone_data.get('description', '')}</small>",
                        unsafe_allow_html=True,
                    )
                if cam_data.get("tripwire"):
                    st.markdown("Tripwire active")

        if layout.get("floor_plan_reference_zones"):
            st.markdown("<p class='section-header' style='margin-top:1rem'>Reference Zones</p>", unsafe_allow_html=True)
            for z_id in layout["floor_plan_reference_zones"]:
                colour = ZONE_COLOURS.get(z_id, DEFAULT_ZONE_COLOUR)
                hex_c = "#{:02x}{:02x}{:02x}".format(*colour[:3])
                st.markdown(
                    f"<span class='zone-badge' style='background:{hex_c}'>{z_id}</span>",
                    unsafe_allow_html=True,
                )


# Zone dwell
def render_zone_dwell(metrics):
    import pandas as pd
    zone_dwell = metrics.get("video_analytics", {}).get("avg_dwell_per_zone_seconds", {})
    if not zone_dwell:
        st.info("No zone dwell data available yet.")
        return

    st.markdown("<p class='section-header'>Average Time Spent per Zone</p>", unsafe_allow_html=True)
    df = (
        pd.DataFrame({"Zone": list(zone_dwell.keys()), "Avg Dwell (seconds)": list(zone_dwell.values())})
        .sort_values("Avg Dwell (seconds)", ascending=False)
    )
    st.bar_chart(df.set_index("Zone"), color="#5B4DA0", height=300)
    st.caption("Higher bars mean visitors spend more time in that zone.")


# Anomalies
SEV_STYLE = {
    "CRITICAL": ("anomaly-critical", "Critical"),
    "WARN":     ("anomaly-warn",     "Warning"),
    "INFO":     ("anomaly-info",     "Info"),
}

def render_anomalies(sid):
    data = get_anomalies(sid)
    if not data or data.get("_error"):
        st.info("Anomaly data is not available right now.")
        return
    logs = data.get("logs", [])
    if not logs:
        st.success("No active anomalies detected.")
        return

    st.markdown("<p class='section-header'>Active Alerts</p>", unsafe_allow_html=True)
    for log in logs:
        sev = log.get("severity", "INFO")
        css_cls, label = SEV_STYLE.get(sev, ("anomaly-info", "Info"))
        atype = log.get("anomaly_type", "UNKNOWN")
        details = log.get("details", "N/A")
        action = log.get("suggested_action", "N/A")
        ts = log.get("timestamp")
        ts_str = f"Offset: {ts:.0f}s" if ts else ""

        st.markdown(
            f"""<div class="anomaly-card {css_cls}">
                <div class="anomaly-title">[{label}] {atype}</div>
                <div class="anomaly-detail">{details}</div>
                <div class="anomaly-action">Suggested action: {action}</div>
                {"<div class='anomaly-action' style='margin-top:4px'>Time: " + ts_str + "</div>" if ts_str else ""}
            </div>""",
            unsafe_allow_html=True,
        )


# Diagnostics
def render_diagnostics(metrics):
    diag = metrics.get("diagnostics", {})
    if not diag:
        st.info("No diagnostic data available.")
        return

    st.markdown("<p class='section-header'>Pipeline Health</p>", unsafe_allow_html=True)
    total_events = diag.get("total_events_ingested", 0)
    unique_vis   = diag.get("total_unique_visitors_tracked", 0)
    frag_status  = diag.get("track_fragmentation_status", "N/A")
    density      = diag.get("event_density_ratio", 0)

    frag_icon = "NORMAL" if frag_status == "NORMAL" else "ELEVATED"

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Events Ingested", f"{total_events:,}")
    with col2:
        st.metric("Unique Visitors Tracked", str(unique_vis))
    with col3:
        st.metric("Track Fragmentation", f"{frag_status} ({frag_icon})")
    with col4:
        st.metric("Events per Visitor", f"{density:.2f}")


# Main
def main():
    render_health()

    meta = STORE_META[selected_store]

    # Page header
    col_title, col_store = st.columns([3, 2])
    with col_title:
        st.title("Live Analytics")
    with col_store:
        st.markdown(
            f"<p style='font-size:13px;color:#888;margin-top:1.6rem'>"
            f"<b style='color:#3D3D3D'>{meta['name']}</b> &nbsp; "
            f"Store ID: <code>{selected_store}</code> &nbsp; "
            f"{'Auto refresh on' if auto_refresh else 'Auto refresh off'}"
            f"</p>",
            unsafe_allow_html=True,
        )

    # Anomaly banner
    render_anomaly_banner(selected_store)
    st.markdown("")

    # Fetch metrics
    metrics = get_metrics(selected_store)

    if metrics and not metrics.get("_error"):
        # KPIs
        render_kpis(metrics)

        # Camera panels
        render_camera_panel(selected_store)
        render_live_cameras(selected_store)
        st.markdown("***")
    else:
        err = (metrics.get("_error", "unknown") if metrics else "API unreachable")
        st.error(f"Could not load store metrics. Error: `{err}`")
        return  

    # Tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Funnel",
        "Heatmap",
        "Zone Layout",
        "Zone Dwell",
        "Anomalies",
        "Diagnostics",
    ])

    with tab1:
        render_funnel(selected_store)

    with tab2:
        render_heatmap_tab(selected_store)

    with tab3:
        render_layout_tab(selected_store)

    with tab4:
        render_zone_dwell(metrics)

    with tab5:
        render_anomalies(selected_store)

    with tab6:
        render_diagnostics(metrics)

    # Auto refresh
    if auto_refresh:
        time.sleep(REFRESH_INTERVAL)
        st.cache_data.clear()
        st.rerun()

main()
