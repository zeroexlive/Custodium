"""Indexing APIs (Phase 5): transaction lookup (replacing the
Phase 1 501 gate) and per-wallet deposit history.

The lookup implements the Phase 0 normative design
(`docs/api/transaction-lookup.md`) against the local index:

- The response is built through the privacy projection: a caller
  sees full platform detail only for transactions belonging to
  THEIR tenant. A transaction indexed for another tenant returns
  exactly the public on-chain minimum (network, hash, block,
  status, confirmations, raw transfers) with
  `belongs_to_tenant: false` and no platform metadata — the same
  shape a purely external indexed transaction would get, so the
  endpoint is not an existence oracle.
- A hash absent from the index is a 404, identical whether it
  never existed or belongs to state the caller may not learn
  about. RPC fallback (design step 6) is policy-gated OFF in this
  phase: local-index data only, never a fabricated result.
- Every lookup writes an audit event (design step 10) without
  other tenants' identifiers.

Projects: machine keys are bound to their key's project; dashboard
users either name a project (membership-checked) or search across
all projects of organizations they belong to.
"""

from __future__ import annotations

import re

from ninja import Router
from ninja.errors import HttpError

from waas.api.authentication import AnyAuth
from waas.api.context import has_any_scope, is_machine, resolve_project
from waas.modules.audit.models import AuditEvent
from waas.modules.evm.models import EvmTransaction
from waas.modules.indexing.models import ObservedDeposit
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Membership
from waas.modules.projects.models import Project
from waas.modules.solana.models import SolanaTransaction
from waas.modules.ton.models import TonTransaction
from waas.modules.tron.models import TronTransaction
from waas.modules.wallets.models import Wallet

router = Router(tags=["indexing"])
any_auth = AnyAuth()

_EVM_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")

_STATUS_MAP = {
    ObservedDeposit.Status.PENDING: "pending",
    ObservedDeposit.Status.CREDITED: "confirmed",
    ObservedDeposit.Status.REORGED_OUT: "failed",
    EvmTransaction.Status.CONFIRMED: "confirmed",
    EvmTransaction.Status.REVERTED: "failed",
    EvmTransaction.Status.FAILED: "failed",
}


def _caller_projects(request, project_id: str | None) -> list[Project]:
    """Projects the caller may see belonging for (see module doc)."""
    if is_machine(request) or project_id:
        return [resolve_project(request, project_id)]
    memberships = Membership.objects.filter(user=request.auth).values_list(
        "organization_id", flat=True
    )
    return list(Project.objects.filter(organization_id__in=list(memberships)))


def _block_value(withdrawal) -> int | None:
    value = getattr(withdrawal, 'block_number', None)
    if value is None:
        value = getattr(withdrawal, 'slot', None)
    return value if value is not None else getattr(withdrawal, 'mc_block_seqno', None)


def _from_of(withdrawal) -> str:
    return getattr(withdrawal, 'from_address', None) or getattr(withdrawal, 'from_raw', '')


def _confirmations(network: BlockchainNetwork, block_number: int | None) -> int | None:
    if block_number is None:
        return None
    cursor = getattr(network, "index_cursor", None)
    if cursor is None:
        return None
    return max(cursor.last_block_number - block_number + 1, 0)


def _public_projection(network: BlockchainNetwork, tx_hash: str) -> dict | None:
    """The public on-chain minimum for an indexed transaction that
    does NOT belong to the caller (or a public view of any indexed
    transaction). Returns None when the hash is not indexed."""
    deposit = (
        ObservedDeposit.objects.filter(network=network, tx_hash=tx_hash)
        .select_related("asset")
        .first()
    )
    if deposit is not None:
        return {
            "network": network.slug,
            "transaction_hash": tx_hash,
            "status": _STATUS_MAP[deposit.status],
            "indexed": True,
            "belongs_to_tenant": False,
            "block_or_slot": deposit.block_number,
            "timestamp": None,
            "confirmations": _confirmations(network, deposit.block_number),
            "matched_addresses": [],
            "transfers": [
                {
                    "transfer_id": f"public:{deposit.id}",
                    "direction": "in",
                    "amount_base_units": str(int(deposit.amount)),
                    "decimals": deposit.asset.decimals,
                    "from": deposit.from_address,
                    "to": deposit.address.address,
                    "asset": deposit.asset.symbol,
                }
            ],
        }
    withdrawal = (
        EvmTransaction.objects.filter(network=network, tx_hash=tx_hash)
        .select_related("asset")
        .first()
    )
    if withdrawal is None:
        tron_tx = (
            TronTransaction.objects.filter(network=network, tx_id=tx_hash)
            .select_related("asset")
            .first()
        )
        if tron_tx is not None:
            withdrawal = tron_tx
    if withdrawal is None:
        withdrawal = (
            SolanaTransaction.objects.filter(network=network, signature=tx_hash)
            .select_related("asset")
            .first()
        )
    if withdrawal is None:
        from django.db.models import Q

        withdrawal = (
            TonTransaction.objects.filter(network=network)
            .filter(Q(tx_hash=tx_hash) | Q(external_message_hash=tx_hash))
            .select_related("asset")
            .first()
        )
    if withdrawal is not None:
        return {
            "network": network.slug,
            "transaction_hash": tx_hash,
            "status": _STATUS_MAP.get(withdrawal.status, "pending"),
            "indexed": True,
            "belongs_to_tenant": False,
            "block_or_slot": _block_value(withdrawal),
            "timestamp": None,
            "confirmations": _confirmations(network, _block_value(withdrawal)),
            "matched_addresses": [],
            "transfers": [
                {
                    "transfer_id": f"public:{withdrawal.id}",
                    "direction": "out",
                    "amount_base_units": str(int(withdrawal.amount)),
                    "decimals": withdrawal.asset.decimals,
                    "from": _from_of(withdrawal),
                    "to": withdrawal.to_address,
                    "asset": withdrawal.asset.symbol,
                }
            ],
        }
    return None


def _tenant_projection(
    network: BlockchainNetwork, tx_hash: str, projects: list[Project]
) -> dict | None:
    """Full platform detail for the caller's own transactions."""
    deposit = (
        ObservedDeposit.objects.filter(
            network=network, tx_hash=tx_hash, wallet__project__in=projects
        )
        .select_related("asset", "address", "wallet")
        .first()
    )
    if deposit is not None:
        wallet = deposit.wallet
        return {
            "network": network.slug,
            "transaction_hash": tx_hash,
            "status": _STATUS_MAP[deposit.status],
            "indexed": True,
            "belongs_to_tenant": True,
            "block_or_slot": deposit.block_number,
            "timestamp": None,
            "confirmations": _confirmations(network, deposit.block_number),
            "matched_addresses": [
                {
                    "address_id": str(deposit.address_id),
                    "wallet_id": str(wallet.id),
                    "external_customer_id": wallet.external_customer_id,
                    "role": "recipient",
                }
            ],
            "transfers": [
                {
                    "transfer_id": str(deposit.id),
                    "direction": "in",
                    "amount_base_units": str(int(deposit.amount)),
                    "decimals": deposit.asset.decimals,
                    "from": deposit.from_address,
                    "to": deposit.address.address,
                    "asset": deposit.asset.symbol,
                }
            ],
            "tenant_record": {
                "type": "deposit",
                "transaction_id": str(deposit.id),
                "wallet_id": str(wallet.id),
                "external_customer_id": wallet.external_customer_id,
                "status": deposit.status,
                "held": deposit.held,
            },
        }
    withdrawal = (
        EvmTransaction.objects.filter(
            network=network, tx_hash=tx_hash, wallet__project__in=projects
        )
        .select_related("asset", "wallet")
        .first()
    )
    if withdrawal is None:
        withdrawal = (
            TronTransaction.objects.filter(
                network=network, tx_id=tx_hash, wallet__project__in=projects
            )
            .select_related("asset", "wallet")
            .first()
        )
    if withdrawal is None:
        withdrawal = (
            SolanaTransaction.objects.filter(
                network=network, signature=tx_hash, wallet__project__in=projects
            )
            .select_related("asset", "wallet")
            .first()
        )
    if withdrawal is None:
        from django.db.models import Q

        withdrawal = (
            TonTransaction.objects.filter(network=network, wallet__project__in=projects)
            .filter(Q(tx_hash=tx_hash) | Q(external_message_hash=tx_hash))
            .select_related("asset", "wallet")
            .first()
        )
    if withdrawal is not None:
        wallet = withdrawal.wallet
        return {
            "network": network.slug,
            "transaction_hash": tx_hash,
            "status": _STATUS_MAP.get(withdrawal.status, "pending"),
            "indexed": True,
            "belongs_to_tenant": True,
            "block_or_slot": _block_value(withdrawal),
            "timestamp": None,
            "confirmations": _confirmations(network, _block_value(withdrawal)),
            "matched_addresses": [
                {
                    "address_id": "",
                    "wallet_id": str(wallet.id),
                    "external_customer_id": wallet.external_customer_id,
                    "role": "sender",
                }
            ],
            "transfers": [
                {
                    "transfer_id": str(withdrawal.id),
                    "direction": "out",
                    "amount_base_units": str(int(withdrawal.amount)),
                    "decimals": withdrawal.asset.decimals,
                    "from": _from_of(withdrawal),
                    "to": withdrawal.to_address,
                    "asset": withdrawal.asset.symbol,
                }
            ],
            "tenant_record": {
                "type": "withdrawal",
                "transaction_id": str(withdrawal.id),
                "wallet_id": str(wallet.id),
                "external_customer_id": wallet.external_customer_id,
                "status": withdrawal.status,
                "held": False,
            },
        }
    return None


@router.get("/transactions/lookup", auth=any_auth)
def lookup_transaction(request, network: str, hash: str, project_id: str | None = None):
    if is_machine(request) and not has_any_scope(request, "transactions:read", "read"):
        raise HttpError(403, "Missing required scope: transactions:read")
    network_obj = BlockchainNetwork.objects.filter(slug=network).first()
    if network_obj is None:
        raise HttpError(422, "Unknown network")
    # Hash format validation per family before any lookup (design §2).
    if network_obj.signature_family == "ecdsa_secp256k1" and network_obj.chain_id is not None:
        if not _EVM_HASH_RE.match(hash):
            raise HttpError(422, "Malformed transaction hash for this network")
    tx_hash = hash if network_obj.signature_family == 'ed25519' else hash.lower()
    projects = _caller_projects(request, project_id)
    result = _tenant_projection(network_obj, tx_hash, projects)
    belongs = result is not None
    if result is None:
        result = _public_projection(network_obj, tx_hash)
    AuditEvent.record(
        "transaction_lookup",
        actor_user=None if is_machine(request) else request.auth,
        organization=projects[0].organization if projects else None,
        project=projects[0] if projects else None,
        metadata={
            "network": network,
            "hash_prefix": tx_hash[:10],
            "belongs_to_tenant": belongs,
            "found": result is not None,
        },
    )
    if result is None:
        raise HttpError(404, "transaction_not_found")
    return result


@router.get("/wallets/{wallet_id}/deposits", auth=any_auth)
def list_wallet_deposits(request, wallet_id: str, project_id: str | None = None):
    """Deposit history for one wallet (newest first)."""
    if is_machine(request) and not has_any_scope(request, "wallets:read", "read"):
        raise HttpError(403, "Missing required scope: wallets:read")
    project = resolve_project(request, project_id)
    wallet = Wallet.objects.filter(id=wallet_id, project=project).first()
    if wallet is None:
        raise HttpError(404, "Wallet not found")
    deposits = (
        ObservedDeposit.objects.filter(wallet=wallet)
        .select_related("asset", "address", "network")
        .order_by("-id")
    )
    return {
        "deposits": [
            {
                "id": str(d.id),
                "network": d.network.slug,
                "tx_hash": d.tx_hash,
                "asset": d.asset.symbol,
                "contract_or_mint_address": d.asset.contract_or_mint_address,
                "amount": str(int(d.amount)),
                "from_address": d.from_address,
                "to_address": d.address.address,
                "status": d.status,
                "held": d.held,
                "block_number": d.block_number,
                "confirmations": _confirmations(d.network, d.block_number),
                "confirmations_required": d.network.confirmations_required,
            }
            for d in deposits
        ],
    }


# ---------------------------------------------------------------- deposit policies

from ninja import Schema as _Schema  # noqa: E402

from waas.api.authentication import DashboardAuth as _DashboardAuth  # noqa: E402

_dashboard_auth = _DashboardAuth()
from waas.modules.assets.models import Asset as _Asset  # noqa: E402
from waas.modules.indexing.models import DepositPolicy as _DepositPolicy  # noqa: E402
from waas.modules.organizations.models import (  # noqa: E402
    Membership as _Membership,
)

_POLICY_MANAGE_ROLES = ("owner", "administrator")


class DepositPolicyIn(_Schema):
    project_id: str
    asset_id: str
    min_amount: str = "0"


def _policy_project(request, project_id: str, *, manage: bool) -> Project:
    project = Project.objects.filter(id=project_id).first()
    if project is None:
        raise HttpError(404, "project not found")
    membership = _Membership.objects.filter(
        organization=project.organization, user=request.actor
    ).first()
    if membership is None:
        raise HttpError(404, "project not found")
    if manage and membership.role not in _POLICY_MANAGE_ROLES:
        raise HttpError(403, "managing deposit policies requires owner or administrator")
    return project


def _policy_out(policy: _DepositPolicy) -> dict:
    return {
        "project_id": str(policy.project_id),
        "asset_id": str(policy.asset_id),
        "asset": policy.asset.symbol,
        "network": policy.asset.network.slug,
        "min_amount": str(int(policy.min_amount)),
    }


@router.get("/deposit-policies", auth=_dashboard_auth, response={200: list[dict], 404: dict})
def list_deposit_policies(request, project_id: str):
    project = _policy_project(request, project_id, manage=False)
    return [
        _policy_out(policy)
        for policy in _DepositPolicy.objects.filter(project=project).select_related("asset__network")
    ]


@router.put(
    "/deposit-policies",
    auth=_dashboard_auth,
    response={200: dict, 403: dict, 404: dict, 422: dict},
)
def put_deposit_policy(request, payload: DepositPolicyIn):
    project = _policy_project(request, payload.project_id, manage=True)
    asset = _Asset.objects.filter(id=payload.asset_id, network__isnull=False).first()
    if asset is None or asset.network_id is None:
        raise HttpError(404, "asset not found")
    try:
        min_amount = int(payload.min_amount)
    except (TypeError, ValueError):
        raise HttpError(422, "min_amount must be an integer in base units") from None
    if min_amount < 0:
        raise HttpError(422, "min_amount cannot be negative")
    policy, _created = _DepositPolicy.objects.update_or_create(
        project=project, asset=asset, defaults={"min_amount": min_amount}
    )
    AuditEvent.record(
        "deposit_policy.updated",
        actor_user=request.actor,
        organization=project.organization,
        project=project,
        metadata={"asset": asset.symbol, "min_amount": str(min_amount)},
    )
    return _policy_out(policy)
