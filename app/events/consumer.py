import traceback
from fastapi import APIRouter, HTTPException, Depends

from app.auth import verify_required
from app.schemas.events_schema import parse_event, EventType
from app.services.notification_service import push_event
from app.repositories.token_repository import get_company_by_token
from app.extensions import get_cached_token_data, set_cached_token_data

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


@router.post("/events/{oa_token}")
async def receive_event(oa_token: str, body: dict):
    """
    Per-tenant endpoint — authenticated via OA token in the URL.
    The token identifies both the company and which OA to push from.
    tenant_id in the payload is ignored — derived from the token.
    """
    # Resolve company from OA token
    token_data = get_cached_token_data(oa_token)
    if not token_data:
        token_row = get_company_by_token(oa_token)
        if not token_row:
            raise HTTPException(status_code=401, detail="Invalid OA token")
        token_data = {
            "company_id":           token_row.company_id,
            "channel_secret":       token_row.channel_secret,
            "channel_access_token": token_row.channel_access_token,
        }
        set_cached_token_data(oa_token, token_data)

    # Inject tenant_id from token — payload's tenant_id is ignored
    body["tenant_id"] = token_data["company_id"]

    try:
        event = parse_event(body)
        dispatch(event)
        return {
            "success":    True,
            "company_id": token_data["company_id"],
            "event_type": event.event_type,
            "trip_id":    event.trip_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
