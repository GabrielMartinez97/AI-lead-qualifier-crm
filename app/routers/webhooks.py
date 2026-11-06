from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.lead import WebhookEventLog
from app.schemas.lead import WebhookIngestResponse
from app.services.webhook_ingestor import ingest_webhook_event, verify_webhook_signature

router = APIRouter(prefix="/webhooks", tags=["Multi-Channel Webhooks"])


@router.post(
    "/leads/{provider}",
    response_model=WebhookIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_lead_webhook(
    provider: str,
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> WebhookIngestResponse:
    """Recibe leads entrantes desde proveedores externos (typeform, meta_ads, linkedin_ads, hubspot, website).
    Valida firma HMAC-SHA256 o token secreto si se envían en cabeceras, normaliza el payload y deduplica por email.
    """
    raw_body = await request.body()
    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"JSON inválido en el cuerpo del webhook: {exc}",
        ) from exc

    sig_valid = verify_webhook_signature(
        raw_body=raw_body,
        signature_header=x_webhook_signature,
        secret_header=x_webhook_secret,
    )

    try:
        return ingest_webhook_event(
            db=db,
            provider=provider,
            payload=payload,
            signature_valid=sig_valid,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/logs")
def list_webhook_logs(
    limit: int = Query(default=30, ge=1, le=100),
    provider: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(WebhookEventLog).order_by(WebhookEventLog.created_at.desc()).limit(limit)
    if provider:
        stmt = stmt.where(WebhookEventLog.provider == provider.strip().lower())
    logs = list(db.scalars(stmt).all())
    return [
        {
            "id": log.id,
            "direction": log.direction,
            "provider": log.provider,
            "event_type": log.event_type,
            "signature_valid": log.signature_valid,
            "status": log.status,
            "lead_id": log.lead_id,
            "error_message": log.error_message,
            "created_at": log.created_at,
        }
        for log in logs
    ]
