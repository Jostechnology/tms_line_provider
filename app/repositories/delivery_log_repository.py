from datetime import datetime
from typing import List
from app.database import SessionLocal, DeliveryLog


def log_push(
    company_id:    str,
    trip_id:       str,
    event_type:    str,
    customer_code: str,
    occurred_at:   datetime,
    status:        str,           # "sent" | "failed" | "no_recipient"
    line_user_id:  str  = None,
    error_detail:  str  = None,
) -> DeliveryLog:
    """Write one delivery log row. Fire-and-forget — caller should not crash on failure here."""
    with SessionLocal() as db:
        row = DeliveryLog(
            company_id=company_id,
            trip_id=trip_id,
            event_type=event_type,
            customer_code=customer_code,
            line_user_id=line_user_id,
            status=status,
            error_detail=error_detail,
            occurred_at=occurred_at,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row


def get_logs_by_trip(trip_id: str, company_id: str) -> List[DeliveryLog]:
    with SessionLocal() as db:
        return (
            db.query(DeliveryLog)
            .filter(DeliveryLog.trip_id == trip_id, DeliveryLog.company_id == company_id)
            .order_by(DeliveryLog.pushed_at)
            .all()
        )


def get_logs_by_tenant(company_id: str, limit: int = 100) -> List[DeliveryLog]:
    with SessionLocal() as db:
        return (
            db.query(DeliveryLog)
            .filter(DeliveryLog.company_id == company_id)
            .order_by(DeliveryLog.pushed_at.desc())
            .limit(limit)
            .all()
        )
