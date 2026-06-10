"""
Event-in schema — frozen contract between TMS and this service.
Payloads carry IDs + scalars + tenant_id only (no nested order graphs).

Event types:
  Transition: wo.started, stop.arrived, stop.delivered, stop.failed,
              stop.departed, stop.load_start, stop.load_end
  Projection: eta.slipped, stop.projected_miss, stop.stalled
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field


# ─── Event type enum ──────────────────────────────────────────────────────────

class EventType(str, Enum):
    WO_STARTED           = "wo.started"
    STOP_ARRIVED         = "stop.arrived"
    STOP_DELIVERED       = "stop.delivered"
    STOP_FAILED          = "stop.failed"
    STOP_DEPARTED        = "stop.departed"
    STOP_LOAD_START      = "stop.load_start"
    STOP_LOAD_END        = "stop.load_end"
    ETA_SLIPPED          = "eta.slipped"
    STOP_PROJECTED_MISS  = "stop.projected_miss"
    STOP_STALLED         = "stop.stalled"


# ─── Base fields shared by every event ───────────────────────────────────────

class BaseEvent(BaseModel):
    event_type:    EventType
    tenant_id:     str = Field(..., description="Company ID — maps to OA registry")
    trip_id:       str = Field(..., description="Work order / trip identifier")
    occurred_at:   datetime = Field(..., description="UTC timestamp of the event")

    class Config:
        use_enum_values = True


# ─── Transition events ────────────────────────────────────────────────────────

class WoStartedEvent(BaseEvent):
    """Work order has been accepted and the trip has begun."""
    event_type:    Literal[EventType.WO_STARTED] = EventType.WO_STARTED
    customer_code: str
    driver_name:   str
    vehicle_plate: str


class StopArrivedEvent(BaseEvent):
    """Driver has arrived at a stop."""
    event_type:    Literal[EventType.STOP_ARRIVED] = EventType.STOP_ARRIVED
    stop_id:       str
    customer_code: str
    stop_address:  str
    eta_minutes:   Optional[int] = None  # how late/early vs. planned


class StopDeliveredEvent(BaseEvent):
    """Goods delivered successfully at a stop."""
    event_type:    Literal[EventType.STOP_DELIVERED] = EventType.STOP_DELIVERED
    stop_id:       str
    customer_code: str
    stop_address:  str
    epod_image_url: Optional[str] = None  # electronic proof-of-delivery photo


class StopFailedEvent(BaseEvent):
    """Delivery attempt failed at a stop."""
    event_type:    Literal[EventType.STOP_FAILED] = EventType.STOP_FAILED
    stop_id:       str
    customer_code: str
    stop_address:  str
    failure_reason: str


class StopDepartedEvent(BaseEvent):
    """Driver has left a stop."""
    event_type:    Literal[EventType.STOP_DEPARTED] = EventType.STOP_DEPARTED
    stop_id:       str
    customer_code: str


class StopLoadStartEvent(BaseEvent):
    """Loading has begun at a stop."""
    event_type:    Literal[EventType.STOP_LOAD_START] = EventType.STOP_LOAD_START
    stop_id:       str
    customer_code: str
    stop_address:  str


class StopLoadEndEvent(BaseEvent):
    """Loading completed at a stop."""
    event_type:    Literal[EventType.STOP_LOAD_END] = EventType.STOP_LOAD_END
    stop_id:       str
    customer_code: str
    stop_address:  str


# ─── Projection events ────────────────────────────────────────────────────────

class EtaSlippedEvent(BaseEvent):
    """ETA has shifted beyond acceptable threshold."""
    event_type:         Literal[EventType.ETA_SLIPPED] = EventType.ETA_SLIPPED
    stop_id:            str
    customer_code:      str
    original_eta:       datetime
    revised_eta:        datetime
    slip_minutes:       int  # positive = later


class StopProjectedMissEvent(BaseEvent):
    """System projects this stop will be missed / very late."""
    event_type:         Literal[EventType.STOP_PROJECTED_MISS] = EventType.STOP_PROJECTED_MISS
    stop_id:            str
    customer_code:      str
    stop_address:       str
    projected_eta:      datetime
    planned_eta:        datetime
    projected_late_minutes: int


class StopStalledEvent(BaseEvent):
    """Vehicle has been stationary unexpectedly for too long."""
    event_type:         Literal[EventType.STOP_STALLED] = EventType.STOP_STALLED
    stop_id:            str
    customer_code:      str
    stalled_minutes:    int
    last_known_address: Optional[str] = None


# ─── Discriminated union — the type used by the consumer ─────────────────────

TripEvent = Union[
    WoStartedEvent,
    StopArrivedEvent,
    StopDeliveredEvent,
    StopFailedEvent,
    StopDepartedEvent,
    StopLoadStartEvent,
    StopLoadEndEvent,
    EtaSlippedEvent,
    StopProjectedMissEvent,
    StopStalledEvent,
]

EVENT_TYPE_MAP: dict[str, type[BaseEvent]] = {
    EventType.WO_STARTED:          WoStartedEvent,
    EventType.STOP_ARRIVED:        StopArrivedEvent,
    EventType.STOP_DELIVERED:      StopDeliveredEvent,
    EventType.STOP_FAILED:         StopFailedEvent,
    EventType.STOP_DEPARTED:       StopDepartedEvent,
    EventType.STOP_LOAD_START:     StopLoadStartEvent,
    EventType.STOP_LOAD_END:       StopLoadEndEvent,
    EventType.ETA_SLIPPED:         EtaSlippedEvent,
    EventType.STOP_PROJECTED_MISS: StopProjectedMissEvent,
    EventType.STOP_STALLED:        StopStalledEvent,
}


def parse_event(data: dict) -> BaseEvent:
    """
    Parse a raw dict into the correct typed event model.
    Raises ValueError for unknown event_type.
    """
    event_type = data.get("event_type")
    model_class = EVENT_TYPE_MAP.get(event_type)
    if not model_class:
        raise ValueError(f"Unknown event_type: {event_type!r}")
    return model_class(**data)
