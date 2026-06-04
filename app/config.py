from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel


class ZoneLayout(BaseModel):
    zone_id: str
    polygon_normalized: List[Tuple[float, float]]
    description: str = ""


class TripwireLayout(BaseModel):
    line_normalized: Tuple[Tuple[float, float], Tuple[float, float]]
    direction_vector: Tuple[float, float]


class CameraLayout(BaseModel):
    camera_id: str
    camera_type: str = "floor"
    description: str = ""
    zones: List[ZoneLayout]
    tripwire: Optional[TripwireLayout] = None
    staff_uniform_hsv_low: Tuple[int, int, int] = (0, 0, 0)
    staff_uniform_hsv_high: Tuple[int, int, int] = (180, 255, 55)
    staff_ratio_threshold: float = 0.55
    velocity_queue_threshold: float = 25.0
    min_queue_dwell_seconds: float = 10.0


class StoreLayout(BaseModel):
    store_id: str
    name: str
    floor_plan_png: str = ""
    cameras: Dict[str, CameraLayout]


LAYOUT_FILE = os.environ.get("LAYOUT_FILE", "/app/data/store_layout.json")


_FALLBACK: dict = {
    "STORE_BLR_001": {
        "store_id": "STORE_BLR_001",
        "store_name": "Purplle — Indiranagar",
        "floor_plan_png": "store1.png",
        "cameras": {
            "CAM_1": {
                "type": "floor",
                "description": "Skincare wall (Farmstay/TFS/Minimalist/Aqualogi/Foxtal/JC)",
                "zones": {
                    "SKINCARE_WALL": {
                        "polygon": [[0.0, 0.0], [0.58, 0.0], [0.58, 0.22], [0.0, 0.22]],
                        "description": "Top wall brand shelves — Salm, TFS, Minimalist, Aqualogi, Foxtal, JC"
                    },
                    "FOH_LEFT": {
                        "polygon": [[0.0, 0.22], [0.58, 0.22], [0.58, 0.75], [0.0, 0.75]],
                        "description": "Left FOH walking area"
                    },
                    "FRAGRANCE_NAIL_UNIT": {
                        "polygon": [[0.27, 0.32], [0.42, 0.32], [0.42, 0.65], [0.27, 0.65]],
                        "description": "Fragrance + Nail counter island"
                    }
                },
                "tripwire": [[0.05, 0.72], [0.95, 0.72]]
            },
            "CAM_2": {
                "type": "floor",
                "description": "Cosmetics/Makeup floor (Loreal/Mars/Lakme/Maybelline/Faces Canada)",
                "zones": {
                    "COSMETICS_WALL": {
                        "polygon": [[0.42, 0.0], [1.0, 0.0], [1.0, 0.22], [0.42, 0.22]],
                        "description": "Bottom wall brand bays — Facia, Mars+Nybae, Mens, Loreal, Beaut"
                    },
                    "MAKEUP_UNIT": {
                        "polygon": [[0.46, 0.28], [0.72, 0.28], [0.72, 0.72], [0.46, 0.72]],
                        "description": "Makeup Unit island (dual chair, 900mm x 900mm per plan)"
                    },
                    "FOH_RIGHT": {
                        "polygon": [[0.15, 0.22], [0.85, 0.22], [0.85, 0.80], [0.15, 0.80]],
                        "description": "Right FOH walking area"
                    }
                },
                "tripwire": [[0.05, 0.75], [0.95, 0.75]]
            },
            "CAM_3": {
                "type": "entry",
                "description": "Entrance — glass door, fisheye top-down",
                "zones": {
                    "ENTRANCE": {
                        "polygon": [[0.30, 0.15], [0.65, 0.10], [0.68, 0.60], [0.28, 0.62]],
                        "description": "Entry threshold (skewed trapezoid due to fisheye)"
                    },
                    "LOBBY": {
                        "polygon": [[0.05, 0.60], [0.95, 0.60], [0.95, 1.0], [0.05, 1.0]],
                        "description": "Just-inside lobby — first ~1.5m after door"
                    }
                },
                "tripwire": [[0.28, 0.38], [0.68, 0.35]]
            },
            "CAM_5": {
                "type": "billing",
                "description": "Cash Counter / Billing + ACCESS corner",
                "zones": {
                    "BILLING": {
                        "polygon": [[0.15, 0.22], [0.75, 0.22], [0.75, 0.72], [0.15, 0.72]],
                        "description": "POS desk + barcode scanner — funnel stage 3"
                    },
                    "CASH_COUNTER": {
                        "polygon": [[0.15, 0.22], [0.75, 0.22], [0.75, 0.72], [0.15, 0.72]],
                        "description": "Alias of BILLING for display purposes"
                    },
                    "ACCESS_CORNER": {
                        "polygon": [[0.75, 0.50], [1.0, 0.50], [1.0, 1.0], [0.75, 1.0]],
                        "description": "Accessories / impulse corner"
                    },
                    "BACKROOM": {
                        "polygon": [[0.0, 0.85], [1.0, 0.85], [1.0, 1.0], [0.0, 1.0]],
                        "description": "Staff-only corridor behind Cash Counter"
                    }
                },
                "tripwire": None
            }
        }
    },
    "STORE_BLR_002": {
        "store_id": "STORE_BLR_002",
        "store_name": "Purplle — Brigade Road",
        "floor_plan_png": "store2.png",
        "cameras": {
            "CAM_4": {
                "type": "backroom",
                "description": "BOH — storeroom (boxes, barrels, makeup chair). Staff-only.",
                "zones": {
                    "BOH": {
                        "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                        "description": "Entire BOH room"
                    },
                    "BACKROOM": {
                        "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                        "description": "Alias used by anomaly engine"
                    }
                },
                "tripwire": None
            }
        },
        "floor_plan_zones_for_reference": {
            "ENTRANCE":         {"polygon": [[0.35, 0.85], [0.65, 0.85], [0.65, 1.0], [0.35, 1.0]]},
            "FOH":              {"polygon": [[0.05, 0.42], [0.95, 0.42], [0.95, 0.85], [0.05, 0.85]]},
            "BOH":              {"polygon": [[0.37, 0.0],  [1.0, 0.0],  [1.0, 0.40], [0.37, 0.40]]},
            "CASH_COUNTER":     {"polygon": [[0.42, 0.37], [0.65, 0.37], [0.65, 0.48], [0.42, 0.48]]},
            "LEFT_WALL_UNITS":  {"polygon": [[0.0, 0.30],  [0.14, 0.30], [0.14, 0.88], [0.0, 0.88]]},
            "RIGHT_WALL_UNITS": {"polygon": [[0.86, 0.30], [1.0, 0.30],  [1.0, 0.88], [0.86, 0.88]]},
            "TOP_WALL_UNITS":   {"polygon": [[0.05, 0.40], [0.95, 0.40], [0.95, 0.50], [0.05, 0.50]]},
            "MAKEUP_UNIT":      {"polygon": [[0.58, 0.55], [0.80, 0.55], [0.80, 0.80], [0.58, 0.80]]},
            "GONDOLA_ZONE":     {"polygon": [[0.15, 0.55], [0.50, 0.55], [0.50, 0.85], [0.15, 0.85]]}
        }
    }
}


class StoreConfigManager:
    def __init__(self, filepath: str = LAYOUT_FILE):
        self.filepath = filepath
        self.stores: Dict[str, StoreLayout] = {}
        self._raw: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, "r") as f:
                data = json.load(f)
            
            data = {k: v for k, v in data.items() if not k.startswith("_")}
        else:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            data = {}


        for sid, fallback in _FALLBACK.items():
            if sid not in data:
                data[sid] = fallback

        self._raw = data

        for store_id, content in data.items():
            if not isinstance(content, dict) or "cameras" not in content:
                continue
            cameras_map: Dict[str, CameraLayout] = {}
            for cam_id, cam_data in content["cameras"].items():
                cam_type = cam_data.get("type", "floor")
                zones_list = self._parse_zones(cam_data)
                tripwire = self._parse_tripwire(cam_type, cam_data)
                cameras_map[cam_id] = CameraLayout(
                    camera_id=cam_id,
                    camera_type=cam_type,
                    description=cam_data.get("description", ""),
                    zones=zones_list,
                    tripwire=tripwire,
                    velocity_queue_threshold=cam_data.get("velocity_queue_threshold", 25.0),
                    min_queue_dwell_seconds=cam_data.get("min_queue_dwell_seconds", 10.0),
                )
            self.stores[store_id] = StoreLayout(
                store_id=store_id,
                name=content.get("store_name", store_id),
                floor_plan_png=content.get("floor_plan_png", ""),
                cameras=cameras_map,
            )

    def _parse_zones(self, cam_data: dict) -> List[ZoneLayout]:
        zones = []
        for z_name, z_data in cam_data.get("zones", {}).items():
            poly = z_data.get("polygon", [[0.0,0.0],[1.0,0.0],[1.0,1.0],[0.0,1.0]])
            desc = z_data.get("description", "")
            zones.append(ZoneLayout(
                zone_id=z_name,
                polygon_normalized=[tuple(p) for p in poly],
                description=desc,
            ))
        if not zones:
            zones.append(ZoneLayout(
                zone_id="SHOPPING_FLOOR",
                polygon_normalized=[(0.0,0.0),(1.0,0.0),(1.0,1.0),(0.0,1.0)],
            ))
        return zones

    def _parse_tripwire(self, cam_type: str, cam_data: dict) -> Optional[TripwireLayout]:
        tw = cam_data.get("tripwire")
        if tw and len(tw) == 2:
            p0, p1 = tw[0], tw[1]
            return TripwireLayout(
                line_normalized=((p0[0], p0[1]), (p1[0], p1[1])),
                direction_vector=(0.0, 1.0),
            )
        if cam_type == "entry":
            return TripwireLayout(
                line_normalized=((0.1, 0.5), (0.9, 0.5)),
                direction_vector=(0.0, 1.0),
            )
        return None

    def get_store(self, store_id: str) -> Optional[StoreLayout]:
        return self.stores.get(store_id)

    def all_store_ids(self) -> List[str]:
        return list(self.stores.keys())

    def get_layout_response(self, store_id: str) -> Optional[dict]:
        """
        Return a JSON-serialisable dict of all zones + tripwires for a store,
        keyed by camera_id.  Used by GET /stores/{id}/layout.
        """
        store = self.stores.get(store_id)
        if not store:
            return None

        cameras_out = {}
        for cam_id, cam in store.cameras.items():
            zones_out = {}
            for z in cam.zones:
                zones_out[z.zone_id] = {
                    "polygon": list(z.polygon_normalized),
                    "description": z.description,
                }
            tw = None
            if cam.tripwire:
                tw = {
                    "line": list(cam.tripwire.line_normalized),
                    "direction_vector": list(cam.tripwire.direction_vector),
                }
            cameras_out[cam_id] = {
                "type": cam.camera_type,
                "description": cam.description,
                "zones": zones_out,
                "tripwire": tw,
            }

        
        raw_store = self._raw.get(store_id, {})
        floor_plan_zones = raw_store.get("floor_plan_zones_for_reference", {})
        fp_out = {}
        for z_name, z_data in floor_plan_zones.items():
            fp_out[z_name] = {"polygon": z_data.get("polygon", [])}

        return {
            "store_id": store_id,
            "store_name": store.name,
            "floor_plan_png": store.floor_plan_png,
            "cameras": cameras_out,
            "floor_plan_reference_zones": fp_out,
            "calibration_note": (
                "Polygons normalised to [0,1] from floor-plan PNG pixel coordinates. "
                "See data/store_layout.json for full methodology."
            ),
        }
