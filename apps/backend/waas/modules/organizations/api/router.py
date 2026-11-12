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


# ------------------------------------------------------- team management
# Phase 11: member administration. Inviting adds an EXISTING
# platform user by email (account creation stays in the identity
# flow). All mutations are owner/administrator-gated and audited;
# the last owner can never be removed or demoted.

from django.contrib.auth import get_user_model  # noqa: E402
from ninja import Schema  # noqa: E402

ADMIN_ROLES = {Membership.Role.OWNER, Membership.Role.ADMINISTRATOR}


class MemberIn(Schema):
    email: str
    role: str = "viewer"


class MemberRoleIn(Schema):
    role: str


def _admin_membership(request, organization_id: str) -> Membership:
    membership = membership_for(request.auth, organization_id)
    if membership is None:
        raise HttpError(404, "Organization not found")
    if membership.role not in ADMIN_ROLES:
        raise HttpError(403, "Member management requires an owner or administrator")
    return membership


def _member_out(membership: Membership) -> dict:
    return {
        "membership_id": str(membership.id),
        "user_id": str(membership.user_id),
        "email": membership.user.email,
        "role": membership.role,
        "created_at": membership.created_at.isoformat(),
    }


@router.get("/organizations/{organization_id}/members", response=dict, auth=dashboard_auth)
def list_members(request, organization_id: str):
    if membership_for(request.auth, organization_id) is None:
        raise HttpError(404, "Organization not found")
    members = (
        Membership.objects.filter(organization_id=organization_id)
        .select_related("user")
        .order_by("created_at")
    )
    return paginated(_member_out(m) for m in members)


@router.post(
    "/organizations/{organization_id}/members",
    response={201: dict, 403: dict, 404: dict, 422: dict},
    auth=dashboard_auth,
)
def add_member(request, organization_id: str, payload: MemberIn):
    admin = _admin_membership(request, organization_id)
    if payload.role not in Membership.Role.values:
        raise HttpError(422, "unknown role")
    user = get_user_model().objects.filter(email=payload.email.strip().lower()).first()
    if user is None:
        raise HttpError(404, "no platform user with that email")
    membership, created = Membership.objects.get_or_create(
        organization_id=organization_id, user=user, defaults={"role": payload.role}
    )
    if not created:
        raise HttpError(422, "user is already a member")
    AuditEvent.record(
        "organization.member_added",
        actor_user=request.auth,
        organization=admin.organization,
        metadata={"member": str(user.id), "role": payload.role},
    )
    return Status(201, _member_out(membership))


@router.patch(
    "/organizations/{organization_id}/members/{membership_id}",
    response={200: dict, 403: dict, 404: dict, 422: dict},
    auth=dashboard_auth,
)
def update_member_role(request, organization_id: str, membership_id: str, payload: MemberRoleIn):
    admin = _admin_membership(request, organization_id)
    if payload.role not in Membership.Role.values:
        raise HttpError(422, "unknown role")
    membership = Membership.objects.filter(
        id=membership_id, organization_id=organization_id
    ).first()
    if membership is None:
        raise HttpError(404, "member not found")
    if membership.role == Membership.Role.OWNER and payload.role != Membership.Role.OWNER:
        owners = Membership.objects.filter(
            organization_id=organization_id, role=Membership.Role.OWNER
        ).count()
        if owners <= 1:
            raise HttpError(422, "the last owner cannot be demoted")
    membership.role = payload.role
    membership.save(update_fields=["role"])
    AuditEvent.record(
        "organization.member_role_changed",
        actor_user=request.auth,
        organization=admin.organization,
        metadata={"member": str(membership.user_id), "role": payload.role},
    )
    return _member_out(membership)


@router.delete(
    "/organizations/{organization_id}/members/{membership_id}",
    response={200: dict, 403: dict, 404: dict, 422: dict},
    auth=dashboard_auth,
)
def remove_member(request, organization_id: str, membership_id: str):
    admin = _admin_membership(request, organization_id)
    membership = Membership.objects.filter(
        id=membership_id, organization_id=organization_id
    ).first()
    if membership is None:
        raise HttpError(404, "member not found")
    if membership.role == Membership.Role.OWNER:
        owners = Membership.objects.filter(
            organization_id=organization_id, role=Membership.Role.OWNER
        ).count()
        if owners <= 1:
            raise HttpError(422, "the last owner cannot be removed")
    user_id = str(membership.user_id)
    membership.delete()
    AuditEvent.record(
        "organization.member_removed",
        actor_user=request.auth,
        organization=admin.organization,
        metadata={"member": user_id},
    )
    return {"removed": user_id}
