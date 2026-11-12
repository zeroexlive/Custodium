from __future__ import annotations

from ninja import Schema


class OrganizationIn(Schema):
    name: str


class OrganizationOut(Schema):
    id: str
    name: str
    slug: str
    role: str | None = None
    created_at: str | None = None


def org_out(org: object, role: str | None = None) -> dict:
    return {
        "id": str(org.id),  # type: ignore[attr-defined]
        "name": org.name,  # type: ignore[attr-defined]
        "slug": org.slug,  # type: ignore[attr-defined]
        "role": role,
        "created_at": org.created_at.isoformat() if getattr(org, "created_at", None) else None,  # type: ignore[attr-defined]
    }
