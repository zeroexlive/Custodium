from __future__ import annotations

from ninja import Schema


class BlacklistEntryIn(Schema):
    scope: str  # platform | tenant
    organization_id: str | None = None
    project_id: str | None = None
    network: str  # network slug
    address: str
    reason: str
    expires_at: str | None = None  # ISO-8601


def entry_out(entry: object) -> dict:
    return {
        "id": str(entry.id),  # type: ignore[attr-defined]
        "scope": entry.scope,  # type: ignore[attr-defined]
        "organization_id": str(entry.organization_id) if entry.organization_id else None,  # type: ignore[attr-defined]
        "project_id": str(entry.project_id) if entry.project_id else None,  # type: ignore[attr-defined]
        "network": entry.network.slug,  # type: ignore[attr-defined]
        "address": entry.address,  # type: ignore[attr-defined]
        "normalized_address": entry.normalized_address,  # type: ignore[attr-defined]
        "reason": entry.reason,  # type: ignore[attr-defined]
        "active": entry.active,  # type: ignore[attr-defined]
        "effective": entry.is_effective,  # type: ignore[attr-defined]
        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,  # type: ignore[attr-defined]
        "created_at": entry.created_at.isoformat() if entry.created_at else None,  # type: ignore[attr-defined]
    }
