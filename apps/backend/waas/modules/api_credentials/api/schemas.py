from __future__ import annotations

from datetime import datetime

from ninja import Schema


class ApiKeyIn(Schema):
    project_id: str
    name: str
    scopes: list[str] = []
    # Optional hardening, enforced by the machine-auth layer when
    # set (waas/api/authentication.py): source IPs allowed to use
    # the key, and an expiry after which the key stops working.
    ip_allowlist: list[str] = []
    expires_at: datetime | None = None


def api_key_out(key: object) -> dict:
    """Public view of an API key. NEVER includes secret material or ciphertext."""
    return {
        "id": str(key.id),  # type: ignore[attr-defined]
        "project_id": str(key.project_id),  # type: ignore[attr-defined]
        "name": key.name,  # type: ignore[attr-defined]
        "key_id": key.key_id,  # type: ignore[attr-defined]
        "scopes": list(key.scopes),  # type: ignore[attr-defined]
        "ip_allowlist": list(key.ip_allowlist or []),  # type: ignore[attr-defined]
        "status": key.status,  # type: ignore[attr-defined]
        "created_at": key.created_at.isoformat() if getattr(key, "created_at", None) else None,  # type: ignore[attr-defined]
        "expires_at": key.expires_at.isoformat() if getattr(key, "expires_at", None) else None,  # type: ignore[attr-defined]
        "last_used_at": key.last_used_at.isoformat() if getattr(key, "last_used_at", None) else None,  # type: ignore[attr-defined]
    }
