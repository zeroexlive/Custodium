"""Gas station API (dashboard): per-(project, network) station
configuration and the top-up history. Machine access is not
offered: funding-wallet selection is an operator decision.
"""

from __future__ import annotations

from ninja import Router, Schema
from ninja.errors import HttpError

from waas.api.authentication import DashboardAuth
from waas.api.context import resolve_project
from waas.modules.audit.models import AuditEvent
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Membership
from waas.modules.wallets.models import Wallet

from ..models import GasStation, GasTopUp

dashboard_router = Router(tags=["gas-station"], auth=DashboardAuth())

MANAGER_ROLES = ("owner", "administrator")


class StationIn(Schema):
    project_id: str
    network: str
    funding_wallet_id: str
    min_native_balance: str
    topup_amount: str
    max_topups_per_day: int = 100
    enabled: bool = True


def _role(request, project):
    membership = Membership.objects.filter(
        organization=project.organization, user=request.actor
    ).first()
    return membership.role if membership else None


def _station_out(station: GasStation) -> dict:
    return {
        "id": str(station.id),
        "project_id": str(station.project_id),
        "network": station.network.slug,
        "funding_wallet_id": str(station.funding_wallet_id),
        "enabled": station.enabled,
        "min_native_balance": str(station.min_native_balance),
        "topup_amount": str(station.topup_amount),
        "max_topups_per_day": station.max_topups_per_day,
    }


@dashboard_router.get("/gas-stations")
def list_stations(request, project_id: str):
    project = resolve_project(request, project_id)
    stations = (
        GasStation.objects.filter(project=project)
        .select_related("network")
        .order_by("network__slug")
    )
    return [_station_out(station) for station in stations]


@dashboard_router.put("/gas-stations", response={200: dict, 403: dict, 404: dict, 422: dict})
def upsert_station(request, payload: StationIn):
    project = resolve_project(request, payload.project_id)
    if _role(request, project) not in MANAGER_ROLES:
        raise HttpError(403, "owner or administrator role required")
    network = BlockchainNetwork.objects.filter(slug=payload.network).first()
    if network is None:
        raise HttpError(404, "unknown network")
    funding_wallet = Wallet.objects.filter(id=payload.funding_wallet_id).first()
    if funding_wallet is None:
        raise HttpError(404, "unknown funding wallet")
    if funding_wallet.project_id != project.id:
        raise HttpError(422, "the funding wallet must belong to the same project")
    try:
        min_balance = int(payload.min_native_balance)
        topup_amount = int(payload.topup_amount)
    except ValueError:
        raise HttpError(422, "amounts must be integer base units") from None
    if min_balance < 0 or topup_amount <= 0:
        raise HttpError(422, "topup_amount must be positive; min_native_balance >= 0")
    if payload.max_topups_per_day < 0:
        raise HttpError(422, "max_topups_per_day must be >= 0")
    station, created = GasStation.objects.update_or_create(
        project=project,
        network=network,
        defaults={
            "funding_wallet": funding_wallet,
            "enabled": payload.enabled,
            "min_native_balance": min_balance,
            "topup_amount": topup_amount,
            "max_topups_per_day": payload.max_topups_per_day,
        },
    )
    AuditEvent.record(
        "gasstation.configured" if created else "gasstation.updated",
        actor_user=request.actor,
        organization=project.organization,
        project=project,
        metadata={
            "station_id": str(station.id),
            "network": network.slug,
            "funding_wallet": str(funding_wallet.id),
            "enabled": payload.enabled,
        },
    )
    return _station_out(station)


@dashboard_router.get("/gas-stations/topups")
def list_topups(request, project_id: str):
    project = resolve_project(request, project_id)
    topups = (
        GasTopUp.objects.filter(station__project=project)
        .select_related("network", "target_wallet")
        .order_by("-created_at")[:100]
    )
    return [
        {
            "id": str(topup.id),
            "network": topup.network.slug,
            "target_wallet_id": str(topup.target_wallet_id),
            "amount": str(topup.amount),
            "status": topup.status,
            "operation_key": topup.operation_key,
            "chain_tx_hash": topup.chain_tx_hash,
            "failure_reason": topup.failure_reason,
            "created_at": topup.created_at.isoformat(),
        }
        for topup in topups
    ]
