import secrets
from typing import Optional, List
from app.database import SessionLocal, LineOAToken


def _generate_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def get_company_by_token(token: str) -> Optional[LineOAToken]:
    with SessionLocal() as db:
        return db.query(LineOAToken).filter(LineOAToken.token == token).first()


def get_tokens_by_company(company_id: str) -> List[LineOAToken]:
    """Returns all OA registrations for a company."""
    with SessionLocal() as db:
        return db.query(LineOAToken).filter(LineOAToken.company_id == company_id).all()


def register_company_token(company_id: str, channel_secret: str, channel_access_token: str) -> tuple:
    """
    If this exact OA channel is already registered under the same company → return existing row, created=False
    If new and the company has no OA yet → create new row, created=True
    If the company already has a different OA → raise ValueError (rejected)

    Policy: one OA per company. The DB schema stays one-to-many (a company *can*
    hold many rows), but this service layer enforces a single OA per company for
    now. Re-syncing the same credentials remains idempotent.
    """
    with SessionLocal() as db:
        # Deduplicate per company — same credentials + same company = already registered
        existing = db.query(LineOAToken).filter(
            LineOAToken.company_id           == company_id,
            LineOAToken.channel_secret       == channel_secret,
            LineOAToken.channel_access_token == channel_access_token,
        ).first()

        if existing:
            return existing, False

        # Reject a second (different) OA for a company that already has one.
        if db.query(LineOAToken).filter(LineOAToken.company_id == company_id).first():
            raise ValueError(
                f"company_id {company_id} already has an OA registered; "
                "only one OA per company is allowed"
            )

        # First OA for this company — generate fresh token
        token = _generate_token()
        new_row = LineOAToken(
            token=token,
            company_id=company_id,
            channel_secret=channel_secret,
            channel_access_token=channel_access_token,
        )
        db.add(new_row)
        db.commit()
        db.refresh(new_row)
        return new_row, True


def update_company_token(token: str, channel_secret: str, channel_access_token: str) -> Optional[LineOAToken]:
    """
    Update credentials for an existing token.
    Used when a company rotates their LINE OA credentials but keeps the same webhook URL.
    """
    with SessionLocal() as db:
        row = db.query(LineOAToken).filter(LineOAToken.token == token).first()
        if not row:
            return None
        row.channel_secret = channel_secret
        row.channel_access_token = channel_access_token
        db.commit()
        db.refresh(row)
        return row


def rotate_token(token: str) -> Optional[str]:
    """Generate a new webhook token for an existing OA registration."""
    with SessionLocal() as db:
        row = db.query(LineOAToken).filter(LineOAToken.token == token).first()
        if not row:
            return None
        row.token = _generate_token()
        db.commit()
        db.refresh(row)
        return row.token


def revoke_token(token: str) -> bool:
    """Remove an OA registration entirely."""
    with SessionLocal() as db:
        row = db.query(LineOAToken).filter(LineOAToken.token == token).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        return True
