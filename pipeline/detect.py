from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, Optional, Set, Tuple

import cv2
import numpy as np
from shapely.geometry import LineString, Point, Polygon
from ultralytics import YOLO

from pipeline.emit import IngestBatchEmitter
from pipeline.tracker import CrossCameraReIDEngine, LocalTrackRepairer

FRAME_SKIP = 5
HEATMAP_FLUSH_INTERVAL = 30.0
HEATMAP_SAMPLE_INTERVAL = 1.0
REENTRY_WINDOW_SEC = 60.0
DWELL_EMIT_INTERVAL_MS = 30_000
BILLING_ABANDON_WINDOW_SEC = 15.0

# Staff classification thresholds
STAFF_MIN_LIFETIME_SEC = 30.0          # must be tracked ≥30s before being considered staff
STAFF_COLOR_CONSENSUS = 0.50           # >50% frames black-uniform
STAFF_ZONE_RATIO = 0.65                # >65% time in BILLING/BACKROOM
STAFF_LIFETIME_RATIO = 0.80            # OR >80% of video duration present
STAFF_BACKROOM_VISIT_THRESHOLD = 2     # ≥2 separate backroom entries → strong staff signal
STAFF_CONFIDENCE_THRESHOLD = 0.60      # weighted confidence score to label as staff


class StoreStreamEngine:
    def __init__(
        self,
        store_id: str,
        layout_filepath: str = "/app/data/store_layout.json",
        model_path: str = "yolov8n.pt",
    ):
        self._entry_guard = set()
        self.store_entered_visitors = set()
        self.store_id = store_id
        self.model = YOLO(model_path)
        self.emitter = IngestBatchEmitter()
        self.repairer = LocalTrackRepairer()
        self.reid = CrossCameraReIDEngine()

        self.session_sequences: Dict[str, int] = {}
        self.active_zones: Dict[str, Optional[str]] = {}
        self.zone_entry_ts: Dict[str, float] = {}
        self.completed_visits: Dict[str, float] = {}
        self.left_billing_ts: Dict[str, float] = {}

        self.past_positions: Dict[int, Tuple[float, float, float]] = {}
        self.staff_votes: Dict[int, list] = {}
        self.staff_zone_dwell: Dict[int, float] = {}
        self.track_lifetime: Dict[int, float] = {}
        self.billing_dwell: Dict[int, float] = {}
        self.backroom_visits: Dict[int, int] = {}         
        self.last_zone_per_track: Dict[int, Optional[str]] = {}  

        self.heatmap_bins: Dict[Tuple[int, int], int] = {}
        self.visitor_last_heatmap: Dict[str, float] = {}
        self.last_heatmap_flush: float = 0.0
        self._entry_guard = set()

        with open(layout_filepath, "r") as f:
            data = json.load(f)
        if store_id not in data:
            raise ValueError(f"Store '{store_id}' not found in {layout_filepath}")
        self.store_layout: Dict[str, Any] = data[store_id]

    # Helpers 

    def _black_uniform_ratio(self, frame: np.ndarray, bbox: np.ndarray) -> bool:
        """Returns True if ≥55% of upper-torso pixels are near-black (staff uniform)."""
        x1, y1, x2, y2 = map(int, bbox)
        torso_y2 = int(y1 + (y2 - y1) * 0.30)
        crop = frame[y1:torso_y2, x1:x2]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 255, 55]))
        return float(np.sum(mask > 0)) / mask.size >= 0.55

    def _staff_confidence(
        self,
        tid: int,
        video_duration: float,
    ) -> float:
        """
        Multi-signal staff confidence score in [0, 1].

        Signals:
          1. Black-uniform color consensus (weight 0.30)
          2. Staff-zone dwell ratio (BILLING + BACKROOM) (weight 0.35)
          3. Track lifetime / video duration (weight 0.20)
          4. Backroom visit count ≥ threshold (weight 0.15)

        A pure black-t-shirt customer scores ≤0.30 unless they also hang around
        staff zones and stay for most of the video.
        """
        lifetime = self.track_lifetime.get(tid, 0.0)
        if lifetime < STAFF_MIN_LIFETIME_SEC:
            return 0.0

        votes = self.staff_votes.get(tid, [])
        color_score = (sum(votes) / len(votes)) if votes else 0.0

        zone_ratio = self.staff_zone_dwell.get(tid, 0.0) / lifetime if lifetime > 0 else 0.0
        zone_score = min(zone_ratio / STAFF_ZONE_RATIO, 1.0)

        lifetime_ratio = lifetime / video_duration if video_duration > 0 else 0.0
        lifetime_score = min(lifetime_ratio / STAFF_LIFETIME_RATIO, 1.0)

        backroom_visits = self.backroom_visits.get(tid, 0)
        backroom_score = min(backroom_visits / STAFF_BACKROOM_VISIT_THRESHOLD, 1.0)

        confidence = (
            0.30 * color_score
            + 0.35 * zone_score
            + 0.20 * lifetime_score
            + 0.15 * backroom_score
        )
        return round(confidence, 3)

    def _iso_ts(self, seconds: float) -> str:
        h = int(seconds // 3600) % 24
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"2026-03-03T{h:02d}:{m:02d}:{s:02d}Z"

    def _emit(
            self,
            camera_id: str,
            visitor_id: str,
            event_type: str,
            timestamp: float,
            zone_id: Optional[str],
            dwell_ms: int,
            is_staff: bool,
            conf: float,
            queue_depth: Optional[int] = None,
            sku_zone: Optional[str] = None,
        ):

            # if event_type == "ENTRY":

            #     if visitor_id in self._entry_guard:
            #         return

            #     self._entry_guard.add(visitor_id)

            if event_type == "ENTRY":

                guard_key = f"{self.store_id}_{visitor_id}"

                if guard_key in self._entry_guard:
                    return

                self._entry_guard.add(guard_key)

            key = f"{self.store_id}_{visitor_id}"
            self.session_sequences[key] = self.session_sequences.get(key, 0) + 1

            token = ("VIS_" + visitor_id.replace("_", "").replace("visitor", ""))[:12]

            self.emitter.queue_event({
                "event_id": str(uuid.uuid4()),
                "store_id": self.store_id,
                "camera_id": camera_id,
                "visitor_id": token,
                "event_type": event_type,
                "timestamp": self._iso_ts(timestamp),
                "zone_id": zone_id,
                "dwell_ms": dwell_ms,
                "is_staff": is_staff,
                "confidence": round(float(conf), 2),
                "metadata": {
                    "queue_depth": queue_depth,
                    "sku_zone": sku_zone,
                    "session_seq": self.session_sequences[key],
                },
            })

    # Main processing loop 

    def process_video_feed(self, camera_id: str, video_path: str):
        cam_cfg = self.store_layout.get("cameras", {}).get(camera_id)
        if not cam_cfg:
            print(f"[Pipeline] Camera '{camera_id}' not in layout. Skipping.")
            return

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"[Pipeline] Cannot open video: {video_path}")
            return

        fw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920.0
        fh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080.0
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_duration = total_frames / fps

        # Build zone polygons
        polygons: Dict[str, Polygon] = {}
        sku_map: Dict[str, Optional[str]] = {}

        raw_zones = cam_cfg.get("zones", {})
        if isinstance(raw_zones, dict):
            for z_name, z_data in raw_zones.items():
                pts = [(int(p[0] * fw), int(p[1] * fh)) for p in z_data.get("polygon", [])]
                if len(pts) >= 3:
                    polygons[z_name] = Polygon(pts)
                sku_map[z_name] = z_data.get("sku_zone")
        else:
            for z in raw_zones:
                pts = [(int(p[0] * fw), int(p[1] * fh)) for p in z.get("polygon_normalized", [])]
                if len(pts) >= 3:
                    polygons[z["zone_id"]] = Polygon(pts)
                sku_map[z["zone_id"]] = None

        # Tripwire
        tripwire_line: Optional[LineString] = None
        direction_vec: Optional[np.ndarray] = None
        tw = cam_cfg.get("tripwire")
        if tw:
            pts_raw = tw if isinstance(tw, list) else tw.get("line_normalized", [])
            if len(pts_raw) == 2:
                p1 = (int(pts_raw[0][0] * fw), int(pts_raw[0][1] * fh))
                p2 = (int(pts_raw[1][0] * fw), int(pts_raw[1][1] * fh))
                tripwire_line = LineString([p1, p2])
                direction_vec = np.array([0.0, 1.0])

        billing_poly: Optional[Polygon] = polygons.get("BILLING")
        frame_idx = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % FRAME_SKIP != 0:
                frame_idx += 1
                continue

            ts = frame_idx / fps
            frame_dt = FRAME_SKIP / fps

            results = self.model.track(
                frame, persist=True, classes=[0],
                tracker="bytetrack.yaml", verbose=False,
            )

            active_ids: Set[int] = set()

            if (
                results
                and results[0].boxes is not None
                and results[0].boxes.id is not None
            ):
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.int().cpu().numpy()
                confs = results[0].boxes.conf.cpu().numpy()

    
                queue_depth = 0
                if billing_poly:
                    for box, tid in zip(boxes, track_ids):
                        tid = int(tid)
                        feet = Point((box[0] + box[2]) / 2, box[3])
                        if billing_poly.contains(feet):
                            px, py, pts_ts = self.past_positions.get(
                                tid, ((box[0] + box[2]) / 2, box[3], ts)
                            )
                            dt = ts - pts_ts
                            disp = np.hypot((box[0] + box[2]) / 2 - px, box[3] - py)
                            speed = disp / dt if dt > 0 else 0.0
                            dwell_s = self.billing_dwell.get(tid, 0.0)
                            thresh_v = cam_cfg.get("velocity_queue_threshold", 25.0)
                            thresh_d = cam_cfg.get("min_queue_dwell_seconds", 10.0)
                            if speed < thresh_v and dwell_s >= thresh_d:
                                queue_depth += 1

                # Per-detection pass 
                for box, tid, conf in zip(boxes, track_ids, confs):
                    tid = int(tid)
                    active_ids.add(tid)

                    x1, y1, x2, y2 = box
                    cx = (x1 + x2) / 2
                    feet = Point(cx, y2)
                    bbox_size = (float(x2 - x1), float(y2 - y1))
                    self.repairer.track_bboxes[tid] = bbox_size

                    self.track_lifetime[tid] = self.track_lifetime.get(tid, 0.0) + frame_dt
                    prev_x, prev_y, prev_ts = self.past_positions.get(tid, (cx, float(y2), ts))
                    self.past_positions[tid] = (cx, float(y2), ts)

                    # Zone lookup
                    matched_zone: Optional[str] = None
                    for zid, poly in polygons.items():
                        if poly.contains(feet):
                            matched_zone = zid
                            break

                    # Track staff-zone dwell and billing dwell
                    if matched_zone in ("BILLING", "BACKROOM"):
                        self.staff_zone_dwell[tid] = self.staff_zone_dwell.get(tid, 0.0) + frame_dt
                    if matched_zone == "BILLING":
                        self.billing_dwell[tid] = self.billing_dwell.get(tid, 0.0) + frame_dt

                    # Count distinct backroom entries
                    prev_zone = self.last_zone_per_track.get(tid)
                    if matched_zone == "BACKROOM" and prev_zone != "BACKROOM":
                        self.backroom_visits[tid] = self.backroom_visits.get(tid, 0) + 1
                    self.last_zone_per_track[tid] = matched_zone

                    # Tripwire direction check
                    if tripwire_line is not None and direction_vec is not None:
                        traj = LineString([(prev_x, prev_y), (cx, y2)])
                        if traj.intersects(tripwire_line):
                            move = np.array([cx - prev_x, y2 - prev_y])
                            if np.dot(move, direction_vec) < 0:
                                continue  # outbound crossing — skip

                    # Track repair (same-camera occlusion recovery)
                    visitor_id = self.repairer.repair_track(
                        tid, ts, (float(feet.x), float(feet.y)), bbox_size
                    )

                    # Cross-camera Re-ID (rich descriptor)
                    desc = CrossCameraReIDEngine.build_descriptor(frame, box)
                    reid_id = self.reid.query_match(ts, desc)
                    if reid_id is not None:
                        visitor_id = reid_id
                        self.repairer.track_to_visitor[tid] = visitor_id

                    # Staff classification — multi-signal confidence score
                    is_black = self._black_uniform_ratio(frame, box)
                    if tid not in self.staff_votes:
                        self.staff_votes[tid] = []
                    self.staff_votes[tid].append(is_black)

                    staff_conf = self._staff_confidence(tid, video_duration)
                    is_staff = staff_conf >= STAFF_CONFIDENCE_THRESHOLD

                    # Heatmap sampling
                    last_hm = self.visitor_last_heatmap.get(visitor_id, -HEATMAP_SAMPLE_INTERVAL)
                    if ts - last_hm >= HEATMAP_SAMPLE_INTERVAL:
                        xg = min(int((cx / fw) * 10), 9)
                        yg = min(int((y2 / fh) * 10), 9)
                        self.heatmap_bins[(xg, yg)] = self.heatmap_bins.get((xg, yg), 0) + 1
                        self.visitor_last_heatmap[visitor_id] = ts

                    # Session state machine 
                    if visitor_id not in self.active_zones:
                        self.active_zones[visitor_id] = matched_zone
                        if matched_zone:
                            self.zone_entry_ts[f"{visitor_id}_{matched_zone}"] = ts

                        # if visitor_id in self.completed_visits:
                        #     last_exit = self.completed_visits[visitor_id]
                        #     ev_type = "REENTRY" if (ts - last_exit) <= REENTRY_WINDOW_SEC else "ENTRY"
                        # else:
                        #     ev_type = "ENTRY"

                        # self._emit(camera_id, visitor_id, ev_type, ts, None, 0, is_staff, conf, queue_depth)


                        if visitor_id not in self.store_entered_visitors:

                                self.store_entered_visitors.add(visitor_id)

                                self._emit(
                                    camera_id,
                                    visitor_id,
                                    "ENTRY",
                                    ts,
                                    None,
                                    0,
                                    is_staff,
                                    conf,
                                    queue_depth
                                )

                        elif visitor_id in self.completed_visits:

                                last_exit = self.completed_visits[visitor_id]

                                if (ts - last_exit) <= REENTRY_WINDOW_SEC:

                                    self._emit(
                                        camera_id,
                                        visitor_id,
                                        "REENTRY",
                                        ts,
                                        None,
                                        0,
                                        is_staff,
                                        conf,
                                        queue_depth
                                    )



                        if matched_zone:
                            self._emit(
                                camera_id, visitor_id, "ZONE_ENTER", ts,
                                matched_zone, 0, is_staff, conf, queue_depth,
                                sku_zone=sku_map.get(matched_zone),
                            )
                            if matched_zone == "BILLING" and queue_depth > 0:
                                self._emit(
                                    camera_id, visitor_id, "BILLING_QUEUE_JOIN", ts,
                                    "BILLING", 0, is_staff, conf, queue_depth,
                                )

                    else:
                        current_zone = self.active_zones[visitor_id]

                        if current_zone != matched_zone:
                            entry_key = f"{visitor_id}_{current_zone}"
                            entry_t = self.zone_entry_ts.get(entry_key, ts)
                            dwell_ms = int((ts - entry_t) * 1000)

                            if current_zone is not None:
                                self._emit(
                                    camera_id, visitor_id, "ZONE_EXIT", ts,
                                    current_zone, dwell_ms, is_staff, conf, queue_depth,
                                )
                                if current_zone == "BILLING":
                                    self.left_billing_ts[visitor_id] = ts

                            self.active_zones[visitor_id] = matched_zone
                            if matched_zone:
                                self.zone_entry_ts[f"{visitor_id}_{matched_zone}"] = ts
                                self._emit(
                                    camera_id, visitor_id, "ZONE_ENTER", ts,
                                    matched_zone, 0, is_staff, conf, queue_depth,
                                    sku_zone=sku_map.get(matched_zone),
                                )
                                if matched_zone == "BILLING" and queue_depth > 0:
                                    self._emit(
                                        camera_id, visitor_id, "BILLING_QUEUE_JOIN", ts,
                                        "BILLING", 0, is_staff, conf, queue_depth,
                                    )
                        else:
                            # Continued dwell — emit ZONE_DWELL every 30 s
                            entry_key = f"{visitor_id}_{current_zone}"
                            entry_t = self.zone_entry_ts.get(entry_key, ts)
                            dwell_ms = int((ts - entry_t) * 1000)
                            if dwell_ms >= DWELL_EMIT_INTERVAL_MS and (
                                dwell_ms % DWELL_EMIT_INTERVAL_MS
                            ) < int(frame_dt * 1000):
                                self._emit(
                                    camera_id, visitor_id, "ZONE_DWELL", ts,
                                    current_zone, dwell_ms, is_staff, conf, queue_depth,
                                )

                    # Billing queue abandonment detection
                    if visitor_id in self.left_billing_ts:
                        elapsed = ts - self.left_billing_ts[visitor_id]
                        if elapsed >= BILLING_ABANDON_WINDOW_SEC and matched_zone != "BILLING":
                            self._emit(
                                camera_id, visitor_id, "BILLING_QUEUE_ABANDON", ts,
                                "BILLING", 0, is_staff, conf, queue_depth,
                            )
                            del self.left_billing_ts[visitor_id]

            # Mark disappeared tracks
            prev_active = set(self.past_positions.keys())
            for lost_tid in prev_active - active_ids:
                px, py, _ = self.past_positions.get(lost_tid, (0.0, 0.0, ts))
                self.repairer.mark_lost(lost_tid, ts, (px, py))

            self.repairer.purge_expired(ts)
            self.reid.purge_expired(ts)

            if ts - self.last_heatmap_flush >= HEATMAP_FLUSH_INTERVAL:
                self._flush_heatmap()
                self.last_heatmap_flush = ts

            frame_idx += 1

        # End of video :  emit EXIT for all active visitors
        exit_ts = frame_idx / fps
        # last_frame = frame if "frame" in dir() else np.zeros((int(fh), int(fw), 3), np.uint8)
        if "frame" in dir() and frame is not None:
            last_frame = frame
        else:
            last_frame = np.zeros((int(fh), int(fw), 3), dtype=np.uint8)
        for visitor_id, current_zone in list(self.active_zones.items()):
            entry_key = f"{visitor_id}_{current_zone}"
            entry_t = self.zone_entry_ts.get(entry_key, exit_ts)
            dwell_ms = int((exit_ts - entry_t) * 1000)

            if current_zone:
                self._emit(camera_id, visitor_id, "ZONE_EXIT", exit_ts, current_zone, dwell_ms, False, 1.0, 0)

            self._emit(camera_id, visitor_id, "EXIT", exit_ts, None, dwell_ms, False, 1.0, 0)
            guard_key = f"{self.store_id}_{visitor_id}"
            if guard_key in self._entry_guard:
                self._entry_guard.remove(guard_key)
            self.completed_visits[visitor_id] = exit_ts

            for tid, vid in self.repairer.track_to_visitor.items():
                if vid == visitor_id and tid in self.past_positions:
                    px, py, _ = self.past_positions[tid]
                    bbox = self.repairer.track_bboxes.get(tid, (80.0, 160.0))
                    desc_box = np.array([
                        max(0, px - bbox[0] / 2), max(0, py - bbox[1]),
                        px + bbox[0] / 2, py,
                    ])
                    desc = CrossCameraReIDEngine.build_descriptor(last_frame, desc_box)
                    self.reid.register_exit(visitor_id, exit_ts, desc)
                    break

        self._flush_heatmap()
        self.emitter.flush()
        cap.release()

    def _flush_heatmap(self):
        if not self.heatmap_bins:
            return
        bins = [
            {"x_grid": x, "y_grid": y, "frequency": cnt}
            for (x, y), cnt in self.heatmap_bins.items()
        ]
        self.emitter.flush_heatmap(self.store_id, bins)
        self.heatmap_bins.clear()
