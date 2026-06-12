from typing import Dict, List

from app.database import LineTmsLink, SessionLocal


def get_line_ids_by_tms_ids(tms_ids: List[str]) -> Dict[str, str]:
    """Resolve TMS usernames → their linked LINE user ids.

    Only usernames that completed the LINE account-linking flow appear in the
    result; unlinked usernames are simply absent (caller treats them as skipped).
    """
    if not tms_ids:
        return {}
    with SessionLocal() as db:
        rows = (
            db.query(LineTmsLink)
            .filter(LineTmsLink.tms_id.in_(tms_ids))
            .all()
        )
    return {row.tms_id: row.line_id for row in rows}
