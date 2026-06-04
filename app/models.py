from pydantic import BaseModel, Field
from typing import Optional, List


class EventMetadata(BaseModel):
    queue_depth:  Optional[int] = Field(None, description="Checkout line queue depth")
    sku_zone:     Optional[str] = Field(None, description="Shelf segment tag")
    session_seq:  int           = Field(...,  description="Chronological event order within visitor session")


class EventPayload(BaseModel):
    event_id:   str
    store_id:   str
    camera_id:  str
    visitor_id: str
    event_type: str
    timestamp:  str
    zone_id:    Optional[str] = None
    dwell_ms:   int           = 0
    is_staff:   bool          = False
    confidence: float         = 1.0
    metadata:   EventMetadata


class HeatmapCoordinate(BaseModel):
    x_grid:    int = Field(..., ge=0, le=9)
    y_grid:    int = Field(..., ge=0, le=9)
    frequency: int = 1


class HeatmapBatchPayload(BaseModel):
    store_id: str
    bins:     List[HeatmapCoordinate]
