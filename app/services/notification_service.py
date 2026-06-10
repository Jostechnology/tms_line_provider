"""
notification_service.py

Single entry point for all outbound LINE push notifications.
Flow:
  1. Look up the LINE userId for customer_code + tenant
  2. Use recipient.oa_token to get the exact channel_access_token they registered through
  3. Build the Flex message from templates
  4. Call LINE Push API
  5. Log the attempt (sent / failed / no_recipient)
"""

import traceback
from typing import Optional
from datetime import datetime, timezone

import requests as http_requests

from app.repositories.recipient_repository import get_recipient
from app.repositories.delivery_log_repository import log_push
from app.repositories.token_repository import get_company_by_token, get_tokens_by_company
from app.services import message_templates as tmpl
from app.schemas.events_schema import (
    BaseEvent, EventType,
    WoStartedEvent, StopArrivedEvent, StopDeliveredEvent, StopFailedEvent,
    StopDepartedEvent, StopLoadStartEvent, StopLoadEndEvent,
    EtaSlippedEvent, StopProjectedMissEvent, StopStalledEvent,
)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _get_channel_token(company_id: str, oa_token: Optional[str] = None) -> Optional[str]:
    """
    Resolve the channel_access_token to use for push.
    If the recipient has an oa_token (registered via a specific OA webhook),
    use that OA's credentials directly.
    Falls back to the first registered OA for the company if oa_token is missing
    (e.g. recipients seeded via admin API without an oa_token).
    """
    if oa_token:
        row = get_company_by_token(oa_token)
        if row and row.company_id == company_id:
            return row.channel_access_token
        # oa_token exists but doesn't match this company — fall through to default
        print(f"[notify] oa_token {oa_token[:10]}… doesn't match company={company_id}, falling back")

    # Fallback: use first OA registered for this company
    rows = get_tokens_by_company(company_id)
    if not rows:
        return None
    return rows[0].channel_access_token


def _push_line(line_user_id: str, message: dict, channel_access_token: str) -> None:
    resp = http_requests.post(
        LINE_PUSH_URL,
        headers={
            "Authorization": f"Bearer {channel_access_token}",
            "Content-Type": "application/json",
        },
        json={
            "to": line_user_id,
            "messages": [message],
        },
        timeout=10,
    )
    resp.raise_for_status()


def _build_message(event: BaseEvent) -> Optional[dict]:
    dispatch = {
        EventType.WO_STARTED:          tmpl.wo_started,
        EventType.STOP_ARRIVED:        tmpl.stop_arrived,
        EventType.STOP_DELIVERED:      tmpl.stop_delivered,
        EventType.STOP_FAILED:         tmpl.stop_failed,
        EventType.STOP_DEPARTED:       tmpl.stop_departed,
        EventType.STOP_LOAD_START:     tmpl.stop_load_start,
        EventType.STOP_LOAD_END:       tmpl.stop_load_end,
        EventType.ETA_SLIPPED:         tmpl.eta_slipped,
        EventType.STOP_PROJECTED_MISS: tmpl.stop_projected_miss,
        EventType.STOP_STALLED:        tmpl.stop_stalled,
    }
    fn = dispatch.get(event.event_type)
    return fn(event) if fn else None


# ─── Public API ───────────────────────────────────────────────────────────────

def push_event(event: BaseEvent, customer_code: str) -> None:
    """
    Resolve recipient for customer_code under event.tenant_id, push message, log result.
    Uses recipient.oa_token to route the push via the correct OA.
    Silent events (stop.departed, load_start/end) are skipped with no log.
    Never raises — all failures are caught and logged.
    """
    company_id  = event.tenant_id
    event_type  = event.event_type
    occurred_at = event.occurred_at if isinstance(event.occurred_at, datetime) \
                  else datetime.now(timezone.utc)

    # Build message — None means silent event, nothing to do
    try:
        message = _build_message(event)
    except Exception:
        traceback.print_exc()
        message = None

    if message is None:
        return  # silent event — no push, no log

    # Resolve recipient
    recipient = get_recipient(company_id, customer_code)
    if not recipient:
        log_push(
            company_id=company_id,
            trip_id=event.trip_id,
            event_type=event_type,
            customer_code=customer_code,
            occurred_at=occurred_at,
            status="no_recipient",
            error_detail="No opted-in LINE userId found for customer_code",
        )
        print(f"[notify] no_recipient company={company_id} customer={customer_code} event={event_type}")
        return

    line_user_id = recipient.line_user_id

    # Resolve channel token — use recipient's oa_token for correct OA routing
    channel_token = _get_channel_token(company_id, oa_token=recipient.oa_token)
    if not channel_token:
        log_push(
            company_id=company_id,
            trip_id=event.trip_id,
            event_type=event_type,
            customer_code=customer_code,
            occurred_at=occurred_at,
            status="failed",
            line_user_id=line_user_id,
            error_detail="No OA token registered for tenant",
        )
        print(f"[notify] no_oa_token company={company_id} event={event_type}")
        return

    # Push
    try:
        _push_line(line_user_id, message, channel_token)
        log_push(
            company_id=company_id,
            trip_id=event.trip_id,
            event_type=event_type,
            customer_code=customer_code,
            occurred_at=occurred_at,
            status="sent",
            line_user_id=line_user_id,
        )
        print(f"[notify] sent company={company_id} user={line_user_id} event={event_type} oa={recipient.oa_token}")

    except Exception as e:
        traceback.print_exc()
        log_push(
            company_id=company_id,
            trip_id=event.trip_id,
            event_type=event_type,
            customer_code=customer_code,
            occurred_at=occurred_at,
            status="failed",
            line_user_id=line_user_id,
            error_detail=str(e),
        )
        print(f"[notify] failed company={company_id} user={line_user_id} event={event_type} err={e}")
