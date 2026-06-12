from fastapi import Header, HTTPException, status
from app.config import ADMIN_TOKEN


async def verify_required(authorization: str = Header(...)):
    """
    FastAPI dependency — replaces the Flask @verify_required decorator.
    Usage: router endpoints add `_: None = Depends(verify_required)`
    """
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    parts = authorization.split(" ")
    if len(parts) == 2 and parts[0] == "Bearer":
        token = parts[1]
    else:
        token = authorization

    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
