"""
pipeline/zone_mapper.py — Map pixel coordinates to zone names.

Loads store layout polygons once and provides fast point-in-polygon
lookups used by the detection pipeline every frame.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
from shapely.geometry import Point, Polygon


class ZoneMapper:
    """
    Maps (x, y) pixel coordinates to a named zone for a given camera.

    Usage:
        mapper = ZoneMapper(store_id, camera_id, layout_filepath, frame_w, frame_h)
        zone_name = mapper.lookup(cx, foot_y)   # returns None if outside all zones
    """

    def __init__(
        self,
        store_id: str,
        camera_id: str,
        layout_filepath: str,
        frame_width: float,
        frame_height: float,
    ):
        self.store_id = store_id
        self.camera_id = camera_id
        self.frame_width = frame_width
        self.frame_height = frame_height

        self.polygons: Dict[str, Polygon] = {}
        self.sku_map: Dict[str, Optional[str]] = {}
        self.tripwire: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None

        self._load(layout_filepath)

    def _load(self, filepath: str):
        candidates = [filepath, "data/store_layout.json", "/app/data/store_layout.json"]
        data = {}
        for c in candidates:
            if os.path.exists(c):
                with open(c, "r") as f:
                    data = json.load(f)
                break

        store_data = data.get(self.store_id, {})
        cam_data = store_data.get("cameras", {}).get(self.camera_id, {})
        if not cam_data:
            return

        fw, fh = self.frame_width, self.frame_height
        zones = cam_data.get("zones", {})

        
        if isinstance(zones, dict):
            for z_name, z_data in zones.items():
                pts = z_data.get("polygon", [])
                px_pts = [(int(p[0] * fw), int(p[1] * fh)) for p in pts]
                if len(px_pts) >= 3:
                    self.polygons[z_name] = Polygon(px_pts)
                self.sku_map[z_name] = z_data.get("sku_zone")
        else:
            for z in zones:
                z_name = z["zone_id"]
                pts = z.get("polygon_normalized", [])
                px_pts = [(int(p[0] * fw), int(p[1] * fh)) for p in pts]
                if len(px_pts) >= 3:
                    self.polygons[z_name] = Polygon(px_pts)
                self.sku_map[z_name] = None

        # Tripwire
        tw = cam_data.get("tripwire")
        if tw and isinstance(tw, list) and len(tw) == 2:
            p0, p1 = tw[0], tw[1]
            self.tripwire = (
                (p0[0] * fw, p0[1] * fh),
                (p1[0] * fw, p1[1] * fh),
            )

    def lookup(self, x: float, y: float) -> Optional[str]:
        """
        Return the zone name for pixel coordinate (x, y), or None if
        the point falls outside all registered zones.

        When zones overlap, the first match wins (zones are stored in
        insertion order from the layout JSON).
        """
        pt = Point(x, y)
        for zone_name, poly in self.polygons.items():
            if poly.contains(pt):
                return zone_name
        return None

    def lookup_sku(self, zone_name: str) -> Optional[str]:
        """Return the SKU zone tag for a zone, or None."""
        return self.sku_map.get(zone_name)

    def all_zones(self) -> List[str]:
        """Return all zone names registered for this camera."""
        return list(self.polygons.keys())

    def is_entry_camera(self) -> bool:
        """Return True if this camera has a tripwire defined (entry/exit threshold camera)."""
        return self.tripwire is not None

    def check_tripwire_crossing(
        self,
        prev_x: float,
        prev_y: float,
        curr_x: float,
        curr_y: float,
    ) -> Optional[str]:
        """
        Determine if the trajectory from (prev_x, prev_y) to (curr_x, curr_y)
        crosses the tripwire and in which direction.

        Returns:
          "INBOUND"   — moving toward store interior (positive Y direction)
          "OUTBOUND"  — moving toward exit (negative Y direction)
          None        — no crossing
        """
        if self.tripwire is None:
            return None

        from shapely.geometry import LineString

        traj = LineString([(prev_x, prev_y), (curr_x, curr_y)])
        wire = LineString([self.tripwire[0], self.tripwire[1]])

        if not traj.intersects(wire):
            return None

        
        dy = curr_y - prev_y
        return "INBOUND" if dy >= 0 else "OUTBOUND"
