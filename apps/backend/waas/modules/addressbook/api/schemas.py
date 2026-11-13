from __future__ import annotations

from ninja import Schema


class DestinationIn(Schema):
    project_id: str
    network: str  # network slug
    address: str
    label: str = ""


class AllowlistPolicyIn(Schema):
    project_id: str
    required: bool


def destination_out(entry: object) -> dict:
    return {
        "id": str(entry.id),  # type: ignore[attr-defined]
        "project_id": str(entry.project_id),  # type: ignore[attr-defined]
        "network": entry.network.slug,  # type: ignore[attr-defined]
        "address": entry.address,  # type: ignore[attr-defined]
        "label": entry.label,  # type: ignore[attr-defined]
        "created_at": entry.created_at.isoformat() if entry.created_at else None,  # type: ignore[attr-defined]
    }
