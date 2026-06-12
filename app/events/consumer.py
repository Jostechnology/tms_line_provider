import traceback
from fastapi import APIRouter, HTTPException, Depends

from app.auth import verify_required
from app.schemas.events_schema import parse_event, EventType
from app.services.notification_service import push_event
from app.repositories.token_repository import get_tokens_by_company

router = APIRouter(prefix="/api", tags=["Event Consumer"])


# ─── Dispatcher ───────────────────────────────────────────────────────────────

def dispatch(event) -> None:
    handlers = {
        EventType.WO_STARTED:          handle_wo_started,
        EventType.STOP_ARRIVED:        handle_stop_arrived,
        EventType.STOP_DELIVERED:      handle_stop_delivered,
        EventType.STOP_FAILED:         handle_stop_failed,
        EventType.STOP_DEPARTED:       handle_stop_departed,
        EventType.STOP_LOAD_START:     handle_stop_load_start,
        EventType.STOP_LOAD_END:       handle_stop_load_end,
        EventType.ETA_SLIPPED:         handle_eta_slipped,
        EventType.STOP_PROJECTED_MISS: handle_stop_projected_miss,
        EventType.STOP_STALLED:        handle_stop_stalled,
    }
    handler = handlers.get(event.event_type)
    if handler:
        handler(event)
    else:
        print(f"[consumer] No handler for event_type={event.event_type!r}")


# ─── Handlers ─────────────────────────────────────────────────────────────────

def handle_wo_started(event) -> None:
    push_event(event, customer_code=event.customer_code)

def handle_stop_arrived(event) -> None:
    push_event(event, customer_code=event.customer_code)

def handle_stop_delivered(event) -> None:
    push_event(event, customer_code=event.customer_code)

def handle_stop_failed(event) -> None:
    push_event(event, customer_code=event.customer_code)

def handle_stop_departed(event) -> None:
    print(f"[stop.departed] trip={event.trip_id} stop={event.stop_id}")

def handle_stop_load_start(event) -> None:
    print(f"[stop.load_start] trip={event.trip_id} stop={event.stop_id}")

def handle_stop_load_end(event) -> None:
    print(f"[stop.load_end] trip={event.trip_id} stop={event.stop_id}")

def handle_eta_slipped(event) -> None:
    push_event(event, customer_code=event.customer_code)

def handle_stop_projected_miss(event) -> None:
    push_event(event, customer_code=event.customer_code)

def handle_stop_stalled(event) -> None:
    push_event(event, customer_code=event.customer_code)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/events", dependencies=[Depends(verify_required)])
async def receive_event_admin(body: dict):
    """
    Admin endpoint — authenticated via ADMIN_TOKEN.
    tenant_id must be provided in the payload.
    Used by TMS backend or internal tooling.
    """
    try:
        event = parse_event(body)
        dispatch(event)
        return {
            "success":    True,
            "event_type": event.event_type,
            "trip_id":    event.trip_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events/{company_id}", dependencies=[Depends(verify_required)])
async def receive_event(company_id: str, body: dict):
    """
    Per-tenant notify endpoint. TMS sends the company_id in the URL; we resolve
    it to the company's registered OA(s) ourselves.

    Authenticated via ADMIN_TOKEN — company_id is an identifier, not a secret,
    so the bearer token (not the path) is what proves the caller is TMS.

    tenant_id in the payload is ignored — derived from the path. The specific OA
    used to push is chosen per-recipient downstream in notification_service.
    """
    # Resolve company_id → registered OA(s). Reject unknown companies.
    if not get_tokens_by_company(company_id):
        raise HTTPException(status_code=404, detail="Unknown company_id — no registered OA")

    body["tenant_id"] = company_id

    try:
        event = parse_event(body)
        dispatch(event)
        return {
            "success":    True,
            "company_id": company_id,
            "event_type": event.event_type,
            "trip_id":    event.trip_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
