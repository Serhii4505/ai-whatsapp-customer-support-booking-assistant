"""FastAPI routes for safe webhook verification and mock ingestion."""

from __future__ import annotations

import json

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import ValidationError

from app.config import Settings
from app.whatsapp.errors import InvalidSignatureError, InvalidWebhookPayloadError
from app.whatsapp.models import WebhookProcessResult
from app.whatsapp.parser import normalize_webhook
from app.whatsapp.repository import WhatsAppRepository
from app.whatsapp.security import verify_challenge, verify_signature


def build_whatsapp_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhook"])
    verify_token = settings.whatsapp_verify_token.get_secret_value()
    app_secret = settings.whatsapp_app_secret.get_secret_value()

    @router.get("", response_class=Response)
    def challenge(
        mode: str | None = Query(default=None, alias="hub.mode"),
        token: str | None = Query(default=None, alias="hub.verify_token"),
        challenge_value: str | None = Query(default=None, alias="hub.challenge", max_length=256),
    ) -> Response:
        if challenge_value is None or not verify_challenge(mode, token, verify_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "verification_failed", "message": "Webhook verification failed"},
            )
        return Response(content=challenge_value, media_type="text/plain", status_code=200)

    @router.post("", response_model=WebhookProcessResult)
    async def receive(
        request: Request,
        x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    ) -> WebhookProcessResult:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > settings.webhook_max_body_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail={"code": "payload_too_large", "message": "Webhook payload exceeds the limit"},
                    )
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "invalid_content_length", "message": "Invalid Content-Length header"},
                ) from None

        body = await request.body()
        if len(body) > settings.webhook_max_body_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={"code": "payload_too_large", "message": "Webhook payload exceeds the limit"},
            )
        try:
            verify_signature(body, x_hub_signature_256, app_secret)
        except InvalidSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "invalid_signature", "message": str(exc)},
            ) from exc

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_json", "message": "Webhook body must be valid JSON"},
            ) from exc

        try:
            batch = normalize_webhook(payload)
        except (InvalidWebhookPayloadError, ValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "invalid_webhook", "message": str(exc)},
            ) from exc

        repository = WhatsAppRepository(settings.database_path, app_secret)
        return repository.process(batch.messages)

    return router
