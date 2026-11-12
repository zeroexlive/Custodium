from __future__ import annotations

from ninja import Schema


class ProjectIn(Schema):
    organization_id: str
    name: str
    environment: str  # sandbox | production


class ProjectOut(Schema):
    id: str
    organization_id: str
    name: str
    environment: str
    created_at: str | None = None


def project_out(project: object) -> dict:
    return {
        "id": str(project.id),  # type: ignore[attr-defined]
        "organization_id": str(project.organization_id),  # type: ignore[attr-defined]
        "name": project.name,  # type: ignore[attr-defined]
        "environment": project.environment,  # type: ignore[attr-defined]
        "created_at": project.created_at.isoformat() if getattr(project, "created_at", None) else None,  # type: ignore[attr-defined]
    }
