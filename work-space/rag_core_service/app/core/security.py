from __future__ import annotations

from fastapi import Header, Request

from app.config import get_settings
from app.errors import ServiceError


async def require_service_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    if request.url.path.endswith("/health"):
        return
    token = get_settings().service_token
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise ServiceError("unauthorized", "Missing or invalid service token", status_code=401)

