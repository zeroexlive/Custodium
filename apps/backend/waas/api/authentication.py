"""Ninja authentication backends.

- DashboardAuth: revocable bearer token issued at login (token hashed at rest).
- HMACAuth: server-to-server API-key HMAC-SHA256 with timestamp + nonce replay
  protection. On success, ``request.api_key`` and ``request.tenant_context``
  are set. Tenant context is ALWAYS derived here, never from request bodies.
- AnyAuth: dashboard token OR HMAC (for shared read endpoints like registries).
"""
from __future__ import annotations

import time
from typing import Any

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone
from ninja.security import HttpBearer

from waas.modules.api_credentials.models import ApiKey, UsedNonce
from waas.modules.identity.models import DashboardToken
from waas.security.hmac.signing import verify as hmac_verify
from waas.security.secret_management.crypto import decrypt_secret


class DashboardAuth(HttpBearer):
    def authenticate(self, request: Any, token: str) -> Any | None:
        user = DashboardToken.resolve(token)
        if user is None:
            return None
        request.actor = user
        request.dashboard_token = token
        return user


class HMACAuth:
    """Callable Ninja auth backend (not bearer-based)."""

    def __call__(self, request: Any) -> Any | None:
        key_id = request.headers.get("X-Api-Key-Id")
        signature = request.headers.get("X-Signature")
        timestamp = request.headers.get("X-Timestamp")
        nonce = request.headers.get("X-Nonce")
        if not all([key_id, signature, timestamp, nonce]):
            return None
        try:
            ts = int(timestamp)
        except (TypeError, ValueError):
            return None
        if abs(int(time.time()) - ts) > settings.HMAC_TIMESTAMP_WINDOW_SECONDS:
            return None
        try:
            api_key = ApiKey.objects.select_related("project", "project__organization").get(key_id=key_id)
        except ApiKey.DoesNotExist:
            return None
        if not api_key.is_usable:
            return None
        if api_key.ip_allowlist:
            remote = request.META.get("REMOTE_ADDR", "")
            if remote not in api_key.ip_allowlist:
                return None
        secret = decrypt_secret(api_key.secret_ciphertext)
        path_with_query = request.get_full_path()
        if not hmac_verify(secret, signature, request.method, path_with_query, str(ts), nonce, request.body):
            return None
        # Replay protection: nonce must be unique per key. Insert AFTER the
        # signature check so attackers cannot burn nonces for valid keys.
        try:
            UsedNonce.objects.create(api_key=api_key, nonce=nonce)
        except IntegrityError:
            return None
        api_key.last_used_at = timezone.now()
        api_key.save(update_fields=["last_used_at"])
        request.api_key = api_key
        request.tenant_context = {
            "organization_id": str(api_key.project.organization_id),
            "project_id": str(api_key.project_id),
            "environment": api_key.project.environment,
            "scopes": list(api_key.scopes),
        }
        return api_key


class AnyAuth:
    """Dashboard bearer token OR machine HMAC — whichever the request carries."""

    def __init__(self) -> None:
        self._dashboard = DashboardAuth()
        self._hmac = HMACAuth()

    def __call__(self, request: Any) -> Any | None:
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            return self._dashboard.authenticate(request, authorization.split(" ", 1)[1].strip())
        if request.headers.get("X-Api-Key-Id"):
            return self._hmac(request)
        return None


def require_scopes(request: Any, *scopes: str) -> bool:
    """HMAC-authenticated requests must carry every required scope."""
    granted = set(getattr(request, "tenant_context", {}).get("scopes", []))
    return all(scope in granted for scope in scopes)
