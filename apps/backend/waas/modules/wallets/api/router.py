from __future__ import annotations

from ninja import Header, Router, Status
from ninja.errors import HttpError

from waas.api.authentication import AnyAuth, DashboardAuth, require_scopes
from waas.api.context import has_any_scope, is_machine, resolve_project
from waas.common.pagination import paginated
from waas.modules.audit.models import AuditEvent
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.api.router import WRITE_ROLES
from waas.modules.organizations.models import Membership
from waas.modules.wallets.api.schemas import ResolveIn, WalletIn, WalletStatusIn, address_out, wallet_out
from waas.modules.wallets.models import Address, Wallet

router = Router(tags=["wallets"])
any_auth = AnyAuth()
dashboard_auth = DashboardAuth()


def _scoped_wallet(request: object, wallet_id: str) -> Wallet:
    wallet = Wallet.objects.select_related("project", "project__organization").filter(id=wallet_id).first()
    if wallet is None:
        raise HttpError(404, "Wallet not found")
    # Re-resolving the wallet's project enforces tenant isolation for both
    # auth kinds (machine: the wallet must belong to the key's project;
    # dashboard: the user must be a member of the wallet's organization).
    resolve_project(request, str(wallet.project_id))
    return wallet


@router.post("/wallets", response={201: dict, 200: dict}, auth=any_auth)
def create_wallet(
    request,
    payload: WalletIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if is_machine(request) and not require_scopes(request, "wallets:write"):
        raise HttpError(403, "Missing required scope: wallets:write")
    project = resolve_project(request, payload.project_id, write=True)
    if payload.wallet_type != Wallet.WalletType.MPC_THRESHOLD:
        raise HttpError(422, "wallet_type must be 'mpc_threshold'")
    label = payload.label.strip()
    if not label:
        raise HttpError(422, "label is required")
    if idempotency_key:
        existing = Wallet.objects.filter(project=project, idempotency_key=idempotency_key).first()
        if existing is not None:
            return Status(200, wallet_out(existing))
    wallet = Wallet.objects.create(
        project=project,
        label=label,
        external_customer_id=payload.external_customer_id.strip(),
        idempotency_key=idempotency_key,
    )
    if is_machine(request):
        AuditEvent.record(
            "wallet.created", organization=project.organization, project=project,
            metadata={"wallet_id": str(wallet.id), "via": "api_key"},
        )
    else:
        AuditEvent.record(
            "wallet.created", actor_user=request.auth,
            organization=project.organization, project=project,
            metadata={"wallet_id": str(wallet.id), "via": "dashboard"},
        )
    return Status(201, wallet_out(wallet))


@router.get("/wallets", response=dict, auth=any_auth)
def list_wallets(
    request,
    project_id: str | None = None,
    external_customer_id: str | None = None,
    status: str | None = None,
):
    if is_machine(request) and not has_any_scope(request, "wallets:read", "read"):
        raise HttpError(403, "Missing required scope: wallets:read")
    project = resolve_project(request, project_id)
    wallets = Wallet.objects.filter(project=project).order_by("created_at")
    if external_customer_id is not None:
        wallets = wallets.filter(external_customer_id=external_customer_id)
    if status is not None:
        wallets = wallets.filter(status=status)
    return paginated(wallet_out(w) for w in wallets)


@router.get("/wallets/{wallet_id}", response=dict, auth=any_auth)
def get_wallet(request, wallet_id: str):
    if is_machine(request) and not has_any_scope(request, "wallets:read", "read"):
        raise HttpError(403, "Missing required scope: wallets:read")
    return wallet_out(_scoped_wallet(request, wallet_id))


@router.patch("/wallets/{wallet_id}/status", response=dict, auth=dashboard_auth)
def set_wallet_status(request, wallet_id: str, payload: WalletStatusIn):
    wallet = _scoped_wallet(request, wallet_id)
    membership = Membership.objects.filter(
        user=request.auth, organization=wallet.project.organization
    ).first()
    if membership is None or membership.role not in WRITE_ROLES:
        raise HttpError(403, "Your role cannot change wallet status")
    target = payload.status
    allowed = {
        Wallet.Status.ACTIVE: {Wallet.Status.FROZEN, Wallet.Status.ARCHIVED},
        Wallet.Status.FROZEN: {Wallet.Status.ACTIVE, Wallet.Status.ARCHIVED},
        Wallet.Status.PROVISIONING: {Wallet.Status.ARCHIVED},
        Wallet.Status.ARCHIVED: set(),
    }
    if target == Wallet.Status.ACTIVE and wallet.status == Wallet.Status.PROVISIONING:
        raise HttpError(
            409,
            "A provisioning wallet becomes active only when MPC key generation "
            "completes (Phase 3); it cannot be activated through the API.",
        )
    if target not in allowed.get(wallet.status, set()):
        raise HttpError(409, f"Cannot move wallet from {wallet.status} to {target}")
    wallet.status = target
    wallet.save(update_fields=["status", "updated_at"])
    AuditEvent.record(
        "wallet.status_changed", actor_user=request.auth,
        organization=wallet.project.organization, project=wallet.project,
        metadata={"wallet_id": str(wallet.id), "status": target},
    )
    return wallet_out(wallet)


@router.get("/wallets/{wallet_id}/addresses", response=dict, auth=any_auth)
def list_addresses(request, wallet_id: str, network: str | None = None):
    if is_machine(request) and not has_any_scope(request, "addresses:read", "wallets:read", "read"):
        raise HttpError(403, "Missing required scope: addresses:read")
    wallet = _scoped_wallet(request, wallet_id)
    addresses = (
        Address.objects.select_related("network").filter(wallet=wallet).order_by("created_at")
    )
    if network:
        addresses = addresses.filter(network__slug=network)
    return paginated(address_out(a) for a in addresses)


@router.post("/wallets/{wallet_id}/addresses", auth=any_auth)
def create_address_not_implemented(request, wallet_id: str):
    # Tenant check first so the gate does not leak wallet existence.
    _scoped_wallet(request, wallet_id)
    raise HttpError(
        501,
        "Address derivation requires MPC key generation (Phase 3) and chain "
        "integration (Phase 4+). No address is fabricated in the meantime.",
    )


@router.post("/addresses/resolve", response=dict, auth=any_auth)
def resolve_address(request, payload: ResolveIn):
    if is_machine(request) and not has_any_scope(request, "addresses:read", "wallets:read", "read"):
        raise HttpError(403, "Missing required scope: addresses:read")
    project = resolve_project(request, payload.project_id)
    network = BlockchainNetwork.objects.filter(slug=payload.network).first()
    if network is None:
        raise HttpError(404, "No address found for that customer and network")
    address = (
        Address.objects.select_related("wallet", "network")
        .filter(
            wallet__project=project,
            wallet__external_customer_id=payload.external_customer_id,
            network=network,
            status=Address.Status.ACTIVE,
        )
        .order_by("created_at")
        .first()
    )
    if address is None:
        raise HttpError(404, "No address found for that customer and network")
    return {
        "wallet_id": str(address.wallet_id),
        "address": address.address,
        "network": network.slug,
        "memo": address.memo,
    }
