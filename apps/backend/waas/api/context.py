"""Tenant-context resolution shared by Phase 2+ routers.

Tenant context is ALWAYS derived from the authenticated identity:
- HMAC machine auth sets ``request.tenant_context`` (project fixed by the
  API key) — a project id in the request must match it or 404.
- Dashboard auth: the user must be a member of the project's
  organization or the project does not exist (404, no oracle).
"""
from __future__ import annotations

from ninja.errors import HttpError

from waas.modules.organizations.api.router import WRITE_ROLES
from waas.modules.organizations.models import Membership
from waas.modules.projects.models import Project


def is_machine(request: object) -> bool:
    return getattr(request, "tenant_context", None) is not None


def has_any_scope(request: object, *scopes: str) -> bool:
    """True when a machine key carries at least one of ``scopes``.

    (``require_scopes`` is all-of; read endpoints accept the specific
    scope OR the generic ``read`` scope, hence this helper.)
    """
    granted = set(getattr(request, "tenant_context", {}).get("scopes", []))
    return any(scope in granted for scope in scopes)


def resolve_project(
    request: object, project_id: str | None = None, *, write: bool = False
) -> Project:
    context = getattr(request, "tenant_context", None)
    if context is not None:
        if project_id is not None and str(project_id) != context["project_id"]:
            raise HttpError(404, "Project not found")
        project = Project.objects.filter(id=context["project_id"]).first()
        if project is None:
            raise HttpError(404, "Project not found")
        return project
    if not project_id:
        raise HttpError(422, "project_id is required")
    project = Project.objects.select_related("organization").filter(id=project_id).first()
    if project is None:
        raise HttpError(404, "Project not found")
    membership = Membership.objects.filter(
        user=request.auth, organization=project.organization  # type: ignore[attr-defined]
    ).first()
    if membership is None:
        raise HttpError(404, "Project not found")
    if write and membership.role not in WRITE_ROLES:
        raise HttpError(403, "Your role cannot perform this operation")
    return project
