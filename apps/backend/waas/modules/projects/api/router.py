from __future__ import annotations

from django.db import IntegrityError, transaction
from ninja import Router, Status
from ninja.errors import HttpError

from waas.api.authentication import DashboardAuth
from waas.common.pagination import paginated
from waas.modules.audit.models import AuditEvent
from waas.modules.organizations.api.router import WRITE_ROLES, membership_for
from waas.modules.organizations.models import Membership
from waas.modules.projects.api.schemas import ProjectIn, project_out
from waas.modules.projects.models import Project

router = Router(tags=["projects"])
dashboard_auth = DashboardAuth()


@router.post("/projects", response={201: dict}, auth=dashboard_auth)
def create_project(request, payload: ProjectIn):
    membership = membership_for(request.auth, payload.organization_id)
    if membership is None:
        raise HttpError(404, "Organization not found")
    if membership.role not in WRITE_ROLES:
        raise HttpError(403, "Your role cannot create projects")
    if payload.environment not in {Project.Environment.SANDBOX, Project.Environment.PRODUCTION}:
        raise HttpError(422, "environment must be 'sandbox' or 'production'")
    name = payload.name.strip()
    if not name:
        raise HttpError(422, "Project name is required")
    try:
        with transaction.atomic():
            project = Project.objects.create(
                organization=membership.organization, name=name,
                environment=payload.environment, created_by=request.auth,
            )
            # William's workflow (2026-11-14): a new project comes with
            # its gas station ready — a dedicated funding wallet plus
            # one station per seeded network to fund for sweep fees.
            from waas.modules.gasstation.services import setup_project_gas_station

            setup_project_gas_station(project, actor_user=request.auth)
    except IntegrityError as exc:
        raise HttpError(409, "A project with that name already exists in this environment") from exc
    AuditEvent.record(
        "project.created", actor_user=request.auth,
        organization=membership.organization, project=project,
    )
    return Status(201, project_out(project))


@router.get("/projects", response=dict, auth=dashboard_auth)
def list_projects(request, organization_id: str | None = None):
    org_ids = Membership.objects.filter(user=request.auth).values_list("organization_id", flat=True)
    projects = Project.objects.filter(organization_id__in=list(org_ids)).order_by("created_at")
    if organization_id:
        projects = projects.filter(organization_id=organization_id)
    return paginated(project_out(p) for p in projects)
