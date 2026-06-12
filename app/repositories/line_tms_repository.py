from typing import Dict, List

from app.database import LineTmsLink, SessionLocal


def upsert_line_tms_link(company_id: str, tms_id: str, line_id: str,
                         oa_token: str = None) -> LineTmsLink:
    """Create or update a (company_id, tms_id) → line_id mapping.

    Keyed by (company_id, tms_id): a LINE userId is per-channel, so the same tms
    username under different tenants maps to different line_ids and must not
    collide. oa_token records which OA channel produced the line_id. Idempotent.
    """
    with SessionLocal() as db:
        row = db.query(LineTmsLink).filter(
            LineTmsLink.company_id == company_id,
            LineTmsLink.tms_id == tms_id,
        ).first()
        if row:
            row.line_id = line_id
            if oa_token is not None:
                row.oa_token = oa_token
        else:
            row = LineTmsLink(company_id=company_id, tms_id=tms_id,
                              line_id=line_id, oa_token=oa_token)
            db.add(row)
        db.commit()
        db.refresh(row)
        return row


def get_line_ids_by_tms_ids(company_id: str, tms_ids: List[str]) -> Dict[str, str]:
    """Resolve a tenant's TMS usernames → their linked LINE user ids.

    Scoped to company_id: line_ids are per-channel, so a username only resolves
    within its own tenant's OA. Only usernames that completed the LINE
    account-linking flow appear; unlinked usernames are absent (caller skips them).
    """
    if not tms_ids:
        return {}
    with SessionLocal() as db:
        rows = (
            db.query(LineTmsLink)
            .filter(
                LineTmsLink.company_id == company_id,
                LineTmsLink.tms_id.in_(tms_ids),
            )
            .all()
        )
    return {row.tms_id: row.line_id for row in rows}
