from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from askhub_ai_server.core.config import Settings, get_settings

USER_ID_HEADER = "x-askhub-user-id"
TEAM_ID_HEADER = "x-askhub-team-id"
TIMESTAMP_HEADER = "x-askhub-timestamp"
SIGNATURE_HEADER = "x-askhub-signature"


@dataclass(frozen=True)
class ServiceContext:
    user_id: int
    team_id: int | None


def _signature_payload(
    *,
    method: str,
    path: str,
    query: str,
    user_id: str,
    team_id: str,
    timestamp: str,
) -> str:
    return "\n".join([timestamp, method.upper(), path, query, user_id, team_id])


def build_service_signature(
    *,
    secret: str,
    method: str,
    path: str,
    query: str = "",
    user_id: int,
    team_id: int | None,
    timestamp: int | None = None,
) -> tuple[str, str]:
    resolved_timestamp = str(timestamp if timestamp is not None else int(time.time()))
    payload = _signature_payload(
        method=method,
        path=path,
        query=query,
        user_id=str(user_id),
        team_id="" if team_id is None else str(team_id),
        timestamp=resolved_timestamp,
    )
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    return resolved_timestamp, signature


def _parse_int_header(value: str, header_name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid {header_name}",
        ) from exc


def _verify_service_request(request: Request, settings: Settings) -> ServiceContext:
    if not settings.service_auth_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service authentication secret is not configured",
        )

    user_id_raw = request.headers.get(USER_ID_HEADER)
    timestamp_raw = request.headers.get(TIMESTAMP_HEADER)
    signature = request.headers.get(SIGNATURE_HEADER)
    team_id_raw = request.headers.get(TEAM_ID_HEADER, "")

    if not user_id_raw or not timestamp_raw or not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="service authentication headers are required",
        )

    timestamp = _parse_int_header(timestamp_raw, TIMESTAMP_HEADER)
    now = int(time.time())
    if abs(now - timestamp) > settings.service_auth_timestamp_tolerance_seconds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="service authentication timestamp is outside the allowed window",
        )

    user_id = _parse_int_header(user_id_raw, USER_ID_HEADER)
    team_id = _parse_int_header(team_id_raw, TEAM_ID_HEADER) if team_id_raw else None
    _, expected_signature = build_service_signature(
        secret=settings.service_auth_secret,
        method=request.method,
        path=request.url.path,
        query=request.url.query,
        user_id=user_id,
        team_id=team_id,
        timestamp=timestamp,
    )
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service authentication signature",
        )

    return ServiceContext(user_id=user_id, team_id=team_id)


def get_service_context(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ServiceContext:
    if not settings.service_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service authentication must be enabled",
        )
    return _verify_service_request(request, settings)
