from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


class LocalTrackRepairer:
    """
    Stitches lost tracks within a single camera.
    When a track ID disappears and a new one appears nearby within
    `temporal_limit` seconds with similar bounding-box dimensions,
    the new track inherits the old visitor_id.
    """

    def __init__(
        self,
        temporal_limit_sec: float = 2.0,
        pixel_distance_limit: float = 120.0,
        bbox_tolerance: float = 0.25,
    ):
        self.temporal_limit = temporal_limit_sec
        self.pixel_distance_limit = pixel_distance_limit
        self.bbox_tolerance = bbox_tolerance

        self.track_to_visitor: Dict[int, str] = {}
        self.lost_tracks: Dict[int, dict] = {}
        self.track_bboxes: Dict[int, Tuple[float, float]] = {}

    def repair_track(
        self,
        local_track_id: int,
        timestamp: float,
        feet_pt: Tuple[float, float],
        bbox_size: Tuple[float, float],
    ) -> str:
        if local_track_id in self.track_to_visitor:
            self.track_bboxes[local_track_id] = bbox_size
            return self.track_to_visitor[local_track_id]

        best_lost_id: Optional[int] = None
        best_dist = float("inf")

        for lost_id, data in list(self.lost_tracks.items()):
            time_diff = timestamp - data["timestamp"]
            if time_diff <= 0 or time_diff > self.temporal_limit:
                continue

            dist = float(np.linalg.norm(np.array(feet_pt) - np.array(data["position"])))
            if dist > self.pixel_distance_limit or dist >= best_dist:
                continue

            lw, lh = data["bbox_size"]
            cw, ch = bbox_size
            if lw == 0 or lh == 0:
                continue
            if (
                abs(cw - lw) / lw <= self.bbox_tolerance
                and abs(ch - lh) / lh <= self.bbox_tolerance
            ):
                best_lost_id = lost_id
                best_dist = dist

        if best_lost_id is not None:
            visitor_id = self.track_to_visitor[best_lost_id]
            del self.lost_tracks[best_lost_id]
        else:
            visitor_id = f"visitor_{local_track_id}"
            print(f"[Tracker] New visitor assigned: track_id={local_track_id} → {visitor_id} (no lost track matched)")

        self.track_to_visitor[local_track_id] = visitor_id
        self.track_bboxes[local_track_id] = bbox_size
        return visitor_id

    def mark_lost(self, track_id: int, timestamp: float, position: Tuple[float, float]):
        if track_id in self.track_to_visitor:
            self.lost_tracks[track_id] = {
                "timestamp": timestamp,
                "position": position,
                "bbox_size": self.track_bboxes.get(track_id, (80.0, 160.0)),
            }

    def purge_expired(self, current_time: float):
        expired = [
            lid for lid, d in self.lost_tracks.items()
            if (current_time - d["timestamp"]) > self.temporal_limit
        ]
        for lid in expired:
            del self.lost_tracks[lid]


def _build_rich_descriptor(frame: np.ndarray, bbox: np.ndarray) -> np.ndarray:
    """
    Build a richer appearance descriptor combining:
      - RGB color histogram (3 × 16 bins = 48 dims) — catches clothing color
      - HSV hue histogram (16 bins) — color-robust under lighting change
      - Bounding-box aspect ratio (1 dim, normalised) — height / width
      - Height estimate (1 dim, normalised 0-1 of frame height) — person scale

    Total: 66 dimensions.  Caller must L2-normalise before cosine comparison.
    """
    x1, y1, x2, y2 = map(int, bbox)
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(fw, x2), min(fh, y2)

    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return np.zeros(66, dtype=np.float32)

    
    th = crop.shape[0]
    torso = crop[th // 4: 3 * th // 4, :]
    if torso.size == 0:
        torso = crop

    # RGB histogram 
    rgb_features: List[float] = []
    for ch in range(3):
        h = cv2.calcHist([torso], [ch], None, [16], [0, 256])
        cv2.normalize(h, h)
        rgb_features.extend(h.flatten().tolist())

    # HSV hue histogram
    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
    hue_hist = cv2.calcHist([hsv], [0], None, [16], [0, 180])
    cv2.normalize(hue_hist, hue_hist)
    hsv_features = hue_hist.flatten().tolist()

    # Geometric features
    height = float(y2 - y1)
    width = float(x2 - x1) if (x2 - x1) > 0 else 1.0
    aspect = min(height / width / 5.0, 1.0)   
    height_norm = min(height / max(fh, 1), 1.0)

    descriptor = np.array(rgb_features + hsv_features + [aspect, height_norm], dtype=np.float32)

    # L2 normalise
    norm = np.linalg.norm(descriptor)
    if norm > 0:
        descriptor /= norm
    return descriptor


class CrossCameraReIDEngine:
    """
    Prevents double-counting across overlapping camera FOVs.

    Descriptor: rich 66-dim vector (RGB histogram + HSV hue + aspect + height).
    Similarity: cosine distance with configurable threshold (default 0.82).

    Improvement over v1 (16-dim grayscale): the colour channels and hue histogram
    distinguish people with different clothing colours that would collide on a
    grayscale histogram, greatly reducing false-positive merges.
    """

    def __init__(
        self,
        handover_window_seconds: float = 5.0,
        similarity_threshold: float = 0.92,
    ):
        self.handover_window = handover_window_seconds
        self.similarity_threshold = similarity_threshold
        self.exit_registry: Dict[str, dict] = {}

    @staticmethod
    def build_descriptor(frame: np.ndarray, bbox: np.ndarray) -> np.ndarray:
        """Public helper so detect.py can call it consistently."""
        return _build_rich_descriptor(frame, bbox)

    def register_exit(
        self, visitor_id: str, timestamp: float, descriptor: np.ndarray
    ):
        self.exit_registry[visitor_id] = {
            "timestamp": timestamp,
            "descriptor": descriptor,
        }

    def query_match(
        self, current_time: float, descriptor: np.ndarray
    ) -> Optional[str]:
        best_id: Optional[str] = None
        best_sim = 0.0

        norm_a = np.linalg.norm(descriptor)
        if norm_a == 0:
            return None

        for v_id, data in list(self.exit_registry.items()):
            elapsed = current_time - data["timestamp"]
            if elapsed < 0 or elapsed > self.handover_window:
                continue
            norm_b = np.linalg.norm(data["descriptor"])
            if norm_b == 0:
                continue
            sim = float(np.dot(descriptor, data["descriptor"]) / (norm_a * norm_b))
            if sim >= self.similarity_threshold and sim > best_sim:
                best_sim = sim
                best_id = v_id

        return best_id

    def purge_expired(self, current_time: float):
        expired = [
            v for v, d in self.exit_registry.items()
            if (current_time - d["timestamp"]) > self.handover_window
        ]
        for v in expired:
            del self.exit_registry[v]
