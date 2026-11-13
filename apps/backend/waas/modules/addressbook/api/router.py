"""Destination address book API (dashboard only).

Managing the book — and toggling the enforcement flag — is
restricted to organization owners/administrators: the book is a
security control, not bookkeeping. Listing is open to any member
who can see the project.
"""
from __future__ import annotations

from ninja import Router, Status
from ninja.errors import HttpError

from waas.api.authentication import DashboardAuth
from waas.api.context import resolve_project
from waas.common.address_normalization import family_for_slug, normalize_address
from waas.common.pagination import paginated
from waas.modules.addressbook.api.schemas import (
    AllowlistPolicyIn,
    DestinationIn,
    destination_out,
)
from waas.modules.addressbook.models import DestinationAddress
from waas.modules.audit.models import AuditEvent
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Membership

router = Router(tags=["address-book"])
dashboard_auth = DashboardAuth()
MANAGE_ROLES = {Membership.Role.OWNER, Membership.Role.ADMINISTRATOR}


def _require_manager(request, project) -> Membership:
    membership = Membership.objects.filter(
        user=request.auth, organization=project.organization
    ).first()
    if membership is None or membership.role not in MANAGE_ROLES:
        raise HttpError(403, "Only organization owners/administrators manage the address book")
    return membership


@router.post("/address-book", response={201: dict, 403: dict, 404: dict, 409: dict, 422: dict}, auth=dashboard_auth)
def add_destination(request, payload: DestinationIn):
    project = resolve_project(request, payload.project_id, write=True)
    _require_manager(request, project)
    network = BlockchainNetwork.objects.filter(slug=payload.network).first()
    if network is None:
        raise HttpError(422, f"unknown network '{payload.network}'")
    try:
        normalized = normalize_address(family_for_slug(network.slug), payload.address)
    except ValueError as exc:
        raise HttpError(422, f"invalid address for {network.slug}: {exc}") from exc
    if DestinationAddress.objects.filter(
        project=project, network=network, normalized_address=normalized
    ).exists():
        raise HttpError(409, "address already in the book for this network")
    entry = DestinationAddress.objects.create(
        project=project,
        network=network,
        address=payload.address.strip(),
        normalized_address=normalized,
        label=payload.label.strip(),
        created_by=request.auth,
    )
    AuditEvent.record(
        "address_book.entry_added", actor_user=request.auth,
        organization=project.organization, project=project,
        metadata={"network": network.slug, "address": entry.address},
    )
    return Status(201, destination_out(entry))


@router.get("/address-book", response=dict, auth=dashboard_auth)
def list_destinations(request, project_id: str):
    project = resolve_project(request, project_id)
    entries = (
        DestinationAddress.objects.select_related("network")
        .filter(project=project)
        .order_by("created_at")
    )
    return paginated(destination_out(e) for e in entries)


@router.get("/address-book/policy", response=dict, auth=dashboard_auth)
def get_policy(request, project_id: str):
    project = resolve_project(request, project_id)
    return {
        "project_id": str(project.id),
        "withdrawal_allowlist_required": bool(project.withdrawal_allowlist_required),
    }


@router.patch("/address-book/policy", response={200: dict, 403: dict, 404: dict}, auth=dashboard_auth)
def set_policy(request, payload: AllowlistPolicyIn):
    project = resolve_project(request, payload.project_id, write=True)
    _require_manager(request, project)
    project.withdrawal_allowlist_required = payload.required
    project.save(update_fields=["withdrawal_allowlist_required", "updated_at"])
    AuditEvent.record(
        "address_book.policy_changed", actor_user=request.auth,
        organization=project.organization, project=project,
        metadata={"withdrawal_allowlist_required": payload.required},
    )
    return {
        "project_id": str(project.id),
        "withdrawal_allowlist_required": payload.required,
    }


@router.delete("/address-book/{entry_id}", response={200: dict, 403: dict, 404: dict}, auth=dashboard_auth)
def remove_destination(request, entry_id: str):
    entry = (
        DestinationAddress.objects.select_related("project")
        .filter(id=entry_id)
        .first()
    )
    if entry is None:
        raise HttpError(404, "entry not found")
    resolve_project(request, str(entry.project_id), write=True)
    _require_manager(request, entry.project)
    entry.delete()
    AuditEvent.record(
        "address_book.entry_removed", actor_user=request.auth,
        organization=entry.project.organization, project=entry.project,
        metadata={"network": entry.network.slug, "address": entry.address},
    )
    return {"detail": "removed"}
