from typing import Optional, List
from app.database import SessionLocal, RecipientLink


def upsert_recipient(
    company_id:    str,
    line_user_id:  str,
    customer_code: Optional[str] = None,
    oa_token:      Optional[str] = None,
    tms_username:  Optional[str] = None,
) -> RecipientLink:
    """
    Create or update the link between a LINE userId and a tenant.
    Lookup priority:
      1. Match by customer_code (webhook/manual registration flow)
      2. Match by tms_username (LINE OAuth flow — no customer_code yet)
    oa_token records which OA the user registered through — used to route
    outbound push notifications back via the correct OA.
    """
    with SessionLocal() as db:
        row = None

        # Try to find existing row by customer_code first
        if customer_code:
            row = db.query(RecipientLink).filter(
                RecipientLink.company_id    == company_id,
                RecipientLink.customer_code == customer_code,
            ).first()

        # Fall back to tms_username lookup (OAuth flow)
        if row is None and tms_username:
            row = db.query(RecipientLink).filter(
                RecipientLink.company_id   == company_id,
                RecipientLink.tms_username == tms_username,
            ).first()

        if row:
            row.line_user_id = line_user_id
            row.opted_in     = True
            if oa_token is not None:
                row.oa_token = oa_token
            if tms_username is not None:
                row.tms_username = tms_username
            if customer_code is not None:
                row.customer_code = customer_code
        else:
            row = RecipientLink(
                company_id=company_id,
                customer_code=customer_code,
                line_user_id=line_user_id,
                oa_token=oa_token,
                tms_username=tms_username,
                opted_in=True,
            )
            db.add(row)

        db.commit()
        db.refresh(row)
        return row


def get_recipient(company_id: str, customer_code: str) -> Optional[RecipientLink]:
    with SessionLocal() as db:
        return db.query(RecipientLink).filter(
            RecipientLink.company_id    == company_id,
            RecipientLink.customer_code == customer_code,
            RecipientLink.opted_in      == True,
        ).first()


def get_recipients_by_user(company_id: str, line_user_id: str) -> List[RecipientLink]:
    with SessionLocal() as db:
        return db.query(RecipientLink).filter(
            RecipientLink.company_id   == company_id,
            RecipientLink.line_user_id == line_user_id,
        ).all()


def opt_out(company_id: str, line_user_id: str) -> bool:
    with SessionLocal() as db:
        rows = db.query(RecipientLink).filter(
            RecipientLink.company_id   == company_id,
            RecipientLink.line_user_id == line_user_id,
        ).all()

        if not rows:
            return False

        for row in rows:
            row.opted_in = False
        db.commit()
        return True
