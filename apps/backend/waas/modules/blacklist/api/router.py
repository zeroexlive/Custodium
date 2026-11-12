"""Manual blacklist management + checks (docs/blacklist/manual-blacklist.md).

This is a manually curated list maintained by humans — not an AML/KYT
system. Tenant entries require a tenant-admin role in that organization;
platform entries require a staff user. Entries are soft-disabled, never
deleted. Check responses reveal only whether a match exists (and which
scope matched), never reasons or notes.
"""
from __future__ import annotations

from datetime import datetime

from django.db.models import Q
from ninja import Router, Status
from ninja.errors import HttpError

from waas.api.authentication import AnyAuth, DashboardAuth
from waas.api.context import has_any_scope, is_machine, resolve_project
from waas.common.address_normalization import family_for_slug, normalize_address
from waas.common.pagination import paginated
from waas.modules.audit.models import AuditEvent
from waas.modules.blacklist import services
from waas.modules.blacklist.api.schemas import BlacklistEntryIn, entry_out
from waas.modules.blacklist.models import BlacklistEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.api.router import membership_for
from waas.modules.organizations.models import Membership
from waas.modules.projects.models import Project

router = Router(tags=["blacklist"])
dashboard_auth = DashboardAuth()
any_auth = AnyAuth()

ADMIN_ROLES = {Membership.Role.OWNER, Membership.Role.ADMINISTRATOR}


def _parse_expiry(value: str | None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HttpError(422, "expires_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise HttpError(422, "expires_at must include a timezone")
    return parsed


@router.get("/blacklist/entries", response=dict, auth=dashboard_auth)
def list_entries(request, organization_id: str):
    membership = membership_for(request.auth, organization_id)
    if membership is None:
        raise HttpError(404, "Organization not found")
    entries = (
        BlacklistEntry.objects.select_related("network")
        .filter(
            Q(scope=BlacklistEntry.Scope.PLATFORM)
            | Q(scope=BlacklistEntry.Scope.TENANT, organization_id=organization_id)
        )
        .order_by("-created_at")
    )
    return paginated(entry_out(e) for e in entries)


@router.post("/blacklist/entries", response={201: dict}, auth=dashboard_auth)
def create_entry(request, payload: BlacklistEntryIn):
    network = BlockchainNetwork.objects.filter(slug=payload.network).first()
    if network is None:
        raise HttpError(422, f"Unknown network '{payload.network}'")
    reason = payload.reason.strip()
    if not reason:
        raise HttpError(422, "A reason is required for every blacklist entry")
    try:
        normalized = normalize_address(family_for_slug(network.slug), payload.address)
    except ValueError as exc:
        raise HttpError(422, str(exc)) from exc

    organization = None
    project = None
    if payload.scope == BlacklistEntry.Scope.PLATFORM:
        if not request.auth.is_staff:
            raise HttpError(403, "Platform entries require a platform operator")
        if payload.organization_id or payload.project_id:
            raise HttpError(422, "Platform entries have no organization/project")
    elif payload.scope == BlacklistEntry.Scope.TENANT:
        if not payload.organization_id:
            raise HttpError(422, "organization_id is required for tenant entries")
        membership = membership_for(request.auth, payload.organization_id)
        if membership is None:
            raise HttpError(404, "Organization not found")
        if membership.role not in ADMIN_ROLES:
            raise HttpError(403, "Tenant blacklist entries require an admin role")
        organization = membership.organization
        if payload.project_id:
            project = Project.objects.filter(
                id=payload.project_id, organization=organization
            ).first()
            if project is None:
                raise HttpError(404, "Project not found")
    else:
        raise HttpError(422, "scope must be 'platform' or 'tenant'")

    entry = BlacklistEntry.objects.create(
        scope=payload.scope,
        organization=organization,
        project=project,
        network=network,
        address=payload.address.strip(),
        normalized_address=normalized,
        reason=reason,
        created_by=request.auth,
        expires_at=_parse_expiry(payload.expires_at),
    )
    AuditEvent.record(
        "blacklist.entry_created", actor_user=request.auth,
        organization=organization, project=project,
        metadata={"entry_id": str(entry.id), "scope": entry.scope, "network": network.slug},
    )
    return Status(201, entry_out(entry))


@router.post("/blacklist/entries/{entry_id}/disable", response=dict, auth=dashboard_auth)
def disable_entry(request, entry_id: str):
    entry = BlacklistEntry.objects.select_related("network").filter(id=entry_id).first()
    if entry is None:
        raise HttpError(404, "Entry not found")
    if entry.scope == BlacklistEntry.Scope.PLATFORM:
        if not request.auth.is_staff:
            raise HttpError(403, "Platform entries require a platform operator")
    else:
        membership = membership_for(request.auth, str(entry.organization_id))
        if membership is None:
            raise HttpError(404, "Entry not found")
        if membership.role not in ADMIN_ROLES:
            raise HttpError(403, "Tenant blacklist entries require an admin role")
    entry.active = False
    entry.save(update_fields=["active", "updated_at"])
    AuditEvent.record(
        "blacklist.entry_disabled", actor_user=request.auth,
        organization=entry.organization, project=entry.project,
        metadata={"entry_id": str(entry.id)},
    )
    return entry_out(entry)


@router.get("/blacklist/check", response=dict, auth=any_auth)
def check_address(
    request,
    address: str,
    network: str,
    organization_id: str | None = None,
    project_id: str | None = None,
):
    net = BlockchainNetwork.objects.filter(slug=network).first()
    if net is None:
        raise HttpError(422, f"Unknown network '{network}'")
    organization = None
    project = None
    if is_machine(request):
        if not has_any_scope(request, "read"):
            raise HttpError(403, "Missing required scope: read")
        project = resolve_project(request, project_id)
        organization = project.organization
    elif organization_id:
        membership = membership_for(request.auth, organization_id)
        if membership is None:
            raise HttpError(404, "Organization not found")
        organization = membership.organization
        if project_id:
            project = Project.objects.filter(id=project_id, organization=organization).first()
            if project is None:
                raise HttpError(404, "Project not found")
    try:
        matches = services.find_matches(
            address=address, network=net, organization=organization, project=project
        )
    except ValueError as exc:
        raise HttpError(422, str(exc)) from exc
    return {
        "blacklisted": bool(matches),
        "matched_scopes": sorted({m.scope for m in matches}),
        "network": net.slug,
    }
