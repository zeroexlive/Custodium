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
from waas.modules.wallets.api.schemas import (
    AddressCreateIn,
    DepositAddressIn,
    ResolveIn,
    WalletIn,
    WalletStatusIn,
    address_out,
    wallet_out,
)
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
    from waas.modules.plans import services as plan_services

    try:
        plan_services.check_wallet_quota(project)
    except plan_services.QuotaExceeded as exc:
        raise HttpError(403, str(exc)) from exc
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
    # A gas sponsor must exist for the project whenever wallets are
    # created: ensure the per-(project, network) gas-station setup is
    # in place. Project creation already ran it; this keeps the
    # guarantee at the wallet-creation point too and heals projects
    # created before the auto-setup existed (checked first so the
    # idempotent setup — and its audit event — only runs when the
    # funding wallet is actually missing).
    from waas.modules.gasstation.services import (
        GAS_STATION_EXTERNAL_ID,
        setup_project_gas_station,
    )

    if not Wallet.objects.filter(
        project=project, external_customer_id=GAS_STATION_EXTERNAL_ID
    ).exists():
        setup_project_gas_station(
            project, actor_user=None if is_machine(request) else request.auth
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


@router.post("/wallets/{wallet_id}/provision", response=dict, auth=dashboard_auth)
def provision_wallet_view(request, wallet_id: str):
    """Run real MPC key generation for this wallet via the signer
    service and activate it (operator action, owner/administrator).

    Fails with 409 — leaving the wallet `provisioning` — while the
    signer gate is closed or the signer service cannot complete
    the ceremonies; see waas.modules.wallets.provisioning.
    """
    from waas.modules.wallets.provisioning import (
        ProvisioningUnavailable,
        provision_wallet,
    )

    wallet = _scoped_wallet(request, wallet_id)
    membership = Membership.objects.filter(
        user=request.auth, organization=wallet.project.organization
    ).first()
    if membership is None or membership.role not in WRITE_ROLES:
        raise HttpError(403, "Your role cannot provision wallets")
    try:
        wallet = provision_wallet(wallet, actor_user=request.auth)
    except ProvisioningUnavailable as exc:
        raise HttpError(409, str(exc)) from exc
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


@router.post(
    "/wallets/{wallet_id}/addresses",
    response={201: dict, 200: dict, 403: dict, 404: dict, 409: dict, 422: dict},
    auth=any_auth,
)
def create_address(request, wallet_id: str, payload: AddressCreateIn):
    """Create (or return) the wallet's address for one network.

    The address comes from the wallet's recorded group public key —
    the same derivation provisioning used — so this works without a
    live signer call once the wallet is provisioned. An
    unprovisioned wallet gets an honest 409: no address is ever
    fabricated for a key that does not exist.
    """
    if is_machine(request) and not has_any_scope(request, "addresses:write", "wallets:write", "write"):
        raise HttpError(403, "Missing required scope: addresses:write")
    wallet = _scoped_wallet(request, wallet_id)
    if not is_machine(request):
        resolve_project(request, str(wallet.project_id), write=True)
    network = BlockchainNetwork.objects.filter(slug=payload.network.strip()).first()
    if network is None:
        raise HttpError(422, f"unknown network: {payload.network}")
    existing = Address.objects.filter(wallet=wallet, network=network).first()
    if existing is not None:
        return Status(200, address_out(existing))
    from waas.modules.wallets.provisioning import (
        ProvisioningUnavailable,
        derive_address_for_network,
    )
    from waas.modules.wallets.services import record_derived_address

    try:
        address = derive_address_for_network(wallet, network)
    except ProvisioningUnavailable as exc:
        raise HttpError(409, str(exc)) from exc
    key_ref = (
        wallet.ecdsa_key_ref
        if network.slug.startswith(("ethereum", "bsc", "tron"))
        else wallet.ed25519_key_ref
    )
    record = record_derived_address(
        wallet=wallet,
        network=network,
        address=address,
        derivation_path=f"signer-service:{key_ref}",
    )
    AuditEvent.record(
        "wallet.address_created",
        actor_user=None if is_machine(request) else request.auth,
        organization=wallet.project.organization,
        project=wallet.project,
        metadata={
            "wallet_id": str(wallet.id),
            "network": network.slug,
            "via": "api_key" if is_machine(request) else "dashboard",
        },
    )
    return Status(201, address_out(record))


# ------------------------------------------------------------ deposit addresses
# A deposit address belongs to one of the customer's end users,
# identified by the customer's own UID (the wallet's
# external_customer_id). Manual mode = the customer enters the UID
# in the dashboard; API mode = the customer's server sends the UID
# and the chain and receives the address. Both hit the same service
# path below; a UID's wallet is found or created, and the address is
# derived from the wallet's MPC group public key — never fabricated
# for an unprovisioned wallet (409).


def _deposit_address_out(address: Address, *, created: bool | None = None) -> dict:
    from waas.modules.indexing.models import ObservedDeposit

    wallet = address.wallet
    deposits = ObservedDeposit.objects.filter(address=address).select_related("asset")
    credited: dict[str, int] = {}
    held = 0
    total = 0
    for deposit in deposits:
        total += 1
        if deposit.held:
            held += 1
        if deposit.status == ObservedDeposit.Status.CREDITED:
            symbol = deposit.asset.symbol
            credited[symbol] = credited.get(symbol, 0) + int(deposit.amount)
    result = {
        **address_out(address),
        "external_customer_id": wallet.external_customer_id,
        "wallet_status": wallet.status,
        "wallet_label": wallet.label,
        "deposits": {
            "count": total,
            "held_count": held,
            "credited_totals": [
                {"asset": symbol, "amount": str(amount)}
                for symbol, amount in sorted(credited.items())
            ],
        },
    }
    if created is not None:
        result["created"] = created
    return result


@router.post(
    "/deposit-addresses",
    response={201: dict, 200: dict, 403: dict, 404: dict, 409: dict, 422: dict},
    auth=any_auth,
)
def create_deposit_address(request, payload: DepositAddressIn):
    """Create (or return) the deposit address for a customer UID on
    one network. Find-or-creates the UID's wallet in the project;
    the address itself is derived from the wallet's recorded group
    public key, so an unprovisioned wallet returns an honest 409
    (provision it from the dashboard first) instead of a fabricated
    address."""
    if is_machine(request) and not has_any_scope(request, "addresses:write", "wallets:write", "write"):
        raise HttpError(403, "Missing required scope: addresses:write")
    project = resolve_project(request, payload.project_id, write=True)
    uid = payload.external_customer_id.strip()
    if not uid or len(uid) > 128:
        raise HttpError(422, "external_customer_id (the customer's user UID) is required")
    from waas.modules.gasstation.services import GAS_STATION_EXTERNAL_ID

    if uid == GAS_STATION_EXTERNAL_ID:
        raise HttpError(422, "that UID is reserved for the project's gas station")
    network = BlockchainNetwork.objects.filter(slug=payload.network.strip()).first()
    if network is None:
        raise HttpError(422, f"unknown network: {payload.network}")

    from django.db import transaction

    # The wallet find-or-create commits on its own: when the wallet
    # is not provisioned yet the endpoint answers 409, and the
    # wallet row must SURVIVE that answer so an operator can
    # provision it and the caller can retry.
    with transaction.atomic():
        wallet = (
            Wallet.objects.filter(project=project, external_customer_id=uid)
            .order_by("created_at")
            .first()
        )
        if wallet is None:
            from waas.modules.plans import services as plan_services

            try:
                plan_services.check_wallet_quota(project)
            except plan_services.QuotaExceeded as exc:
                raise HttpError(403, str(exc)) from exc
            wallet = Wallet.objects.create(
                project=project,
                label=f"Customer {uid}",
                external_customer_id=uid,
            )
            AuditEvent.record(
                "wallet.created",
                actor_user=None if is_machine(request) else request.auth,
                organization=project.organization,
                project=project,
                metadata={
                    "wallet_id": str(wallet.id),
                    "via": "deposit_address",
                    "external_customer_id": uid,
                },
            )
            if not Wallet.objects.filter(
                project=project, external_customer_id=GAS_STATION_EXTERNAL_ID
            ).exists():
                from waas.modules.gasstation.services import setup_project_gas_station

                setup_project_gas_station(
                    project, actor_user=None if is_machine(request) else request.auth
                )
    existing = Address.objects.filter(wallet=wallet, network=network).first()
    if existing is not None:
        return Status(200, _deposit_address_out(existing, created=False))
    from waas.modules.wallets.provisioning import (
        ProvisioningUnavailable,
        derive_address_for_network,
    )
    from waas.modules.wallets.services import record_derived_address

    try:
        derived = derive_address_for_network(wallet, network)
    except ProvisioningUnavailable as exc:
        raise HttpError(
            409,
            f"wallet {wallet.id} for this UID is not provisioned yet: {exc}",
        ) from exc
    key_ref = (
        wallet.ecdsa_key_ref
        if network.slug.startswith(("ethereum", "bsc", "tron"))
        else wallet.ed25519_key_ref
    )
    with transaction.atomic():
        record = record_derived_address(
            wallet=wallet,
            network=network,
            address=derived,
            derivation_path=f"signer-service:{key_ref}",
        )
        AuditEvent.record(
            "deposit_address.created",
            actor_user=None if is_machine(request) else request.auth,
            organization=project.organization,
            project=project,
            metadata={
                "wallet_id": str(wallet.id),
                "external_customer_id": uid,
                "network": network.slug,
                "via": "api_key" if is_machine(request) else "dashboard",
            },
        )
    return Status(201, _deposit_address_out(record, created=True))


@router.get("/deposit-addresses", response=dict, auth=any_auth)
def list_deposit_addresses(
    request,
    project_id: str | None = None,
    external_customer_id: str | None = None,
    address: str | None = None,
    network: str | None = None,
):
    """Search a project's deposit addresses — by address, by
    customer UID, or both — with each address's status and deposit
    summary for troubleshooting."""
    if is_machine(request) and not has_any_scope(request, "addresses:read", "wallets:read", "read"):
        raise HttpError(403, "Missing required scope: addresses:read")
    project = resolve_project(request, project_id)
    addresses = (
        Address.objects.select_related("wallet", "network")
        .filter(wallet__project=project)
        .order_by("created_at")
    )
    if external_customer_id is not None:
        addresses = addresses.filter(wallet__external_customer_id=external_customer_id.strip())
    if address:
        needle = address.strip()
        from django.db.models import Q

        addresses = addresses.filter(
            Q(address__icontains=needle) | Q(normalized_address__icontains=needle.lower())
        )
    if network:
        addresses = addresses.filter(network__slug=network.strip())
    return paginated(_deposit_address_out(a) for a in addresses)


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
