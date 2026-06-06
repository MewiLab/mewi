"""Report read-token helpers.

FastAPI uses AWS IAM to read private S3 objects. This module handles the
application-level question: which player may read which report?
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException, status
from jwt import ExpiredSignatureError, InvalidTokenError


REPORT_READ_ALGORITHM = "HS256"


@dataclass(frozen=True)
class ReportPrincipal:
    user_id: str
    admin: bool = False


def create_report_read_token(
    user_id: str,
    secret: str,
    *,
    expires_delta: timedelta = timedelta(days=30),
    admin: bool = False,
) -> str:
    """Mint a capability token for a report link."""
    if not secret:
        raise ValueError("report read JWT secret is required")
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + expires_delta,
    }
    if admin:
        payload["admin"] = True
    return jwt.encode(payload, secret, algorithm=REPORT_READ_ALGORITHM)


def decode_report_read_token(token: str, secret: str) -> ReportPrincipal:
    """Decode a report capability token into the caller identity."""
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Report read JWT secret is not configured.",
        )
    try:
        claims = jwt.decode(token, secret, algorithms=[REPORT_READ_ALGORITHM])
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Report read token has expired.",
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid report read token.",
        ) from exc

    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid report read token.",
        )
    return ReportPrincipal(user_id=subject, admin=bool(claims.get("admin")))


def authorize_report_user(principal: ReportPrincipal, requested_user_id: str) -> str:
    """Allow admins or the exact subject user, and reject cross-user reads."""
    if principal.admin or principal.user_id == requested_user_id:
        return requested_user_id
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Report token is not authorized for this user.",
    )
