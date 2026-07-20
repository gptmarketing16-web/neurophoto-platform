from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from ..settings import settings

router = APIRouter(prefix="/api/max", tags=["max"])


@router.post("/webhook")
async def max_webhook(
    request: Request,
    x_max_bot_api_secret: str | None = Header(default=None),
) -> dict[str, bool]:
    """MAX transport adapter stub.

    Sprint 1 only validates the webhook secret and acknowledges the event.
    Mapping MAX attachments into jobs is the next integration milestone.
    """
    if settings.max_webhook_secret and x_max_bot_api_secret != settings.max_webhook_secret:
        raise HTTPException(401, "Invalid MAX webhook secret")
    await request.json()
    return {"ok": True}
