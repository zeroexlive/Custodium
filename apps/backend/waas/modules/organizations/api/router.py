from __future__ import annotations

from ninja import Router, Status
from ninja.errors import HttpError

from waas.api.authentication import DashboardAuth
from waas.common.pagination import paginated
from waas.modules.audit.models import AuditEvent
from waas.modules.organizations.api.schemas import OrganizationIn, org_out
from waas.modules.organizations.models import Membership, Organization

router = Router(tags=["organizations"])
dashboard_auth = DashboardAuth()

WRITE_ROLES = {Membership.Role.OWNER, Membership.Role.ADMINISTRATOR, Membership.Role.DEVELOPER}


def membership_for(user: object, organization_id: str) -> Membership | None:
    """Tenant isolation: membership is derived from the authenticated user."""
    return (
        Membership.objects.select_related("organization")
        .filter(user=user, organization_id=organization_id)
        .first()
    )


@router.post("/organizations", response={201: dict}, auth=dashboard_auth)
def create_organization(request, payload: OrganizationIn):
    name = payload.name.strip()
    if not name:
        raise HttpError(422, "Organization name is required")
    org = Organization.create_with_owner(name, request.auth)
    AuditEvent.record("organization.created", actor_user=request.auth, organization=org)
    return Status(201, org_out(org, Membership.Role.OWNER))


@router.get("/organizations", response=dict, auth=dashboard_auth)
def list_organizations(request):
    memberships = (
        Membership.objects.select_related("organization").filter(user=request.auth).order_by("created_at")
    )
    return paginated(org_out(m.organization, m.role) for m in memberships)


@router.get("/organizations/{organization_id}", response=dict, auth=dashboard_auth)
def get_organization(request, organization_id: str):
    membership = membership_for(request.auth, organization_id)
    if membership is None:
        # No existence oracle for other tenants' organizations.
        raise HttpError(404, "Organization not found")
    return org_out(membership.organization, membership.role)
