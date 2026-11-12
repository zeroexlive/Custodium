"""Balance read APIs (docs/api/wallet-api.md §5).

Balances are derived from ledger postings only — never from chain RPC —
and amounts are returned as integer strings (base units), never floats.
"""
from __future__ import annotations

from ninja import Router
from ninja.errors import HttpError

from waas.api.authentication import AnyAuth
from waas.api.context import has_any_scope, is_machine, resolve_project
from waas.modules.ledger import services
from waas.modules.ledger.models import LedgerAccount
from waas.modules.wallets.models import Wallet

router = Router(tags=["balances"])
any_auth = AnyAuth()


def _check_read_scope(request: object) -> None:
    if is_machine(request) and not has_any_scope(request, "wallets:read", "read"):
        raise HttpError(403, "Missing required scope: wallets:read")


def _asset_block(asset, accounts: list[LedgerAccount]) -> dict:
    by_type: dict[str, int] = {}
    for account in accounts:
        by_type[account.account_type] = by_type.get(account.account_type, 0) + services.account_balance(account)
    return {
        "asset_id": str(asset.id),
        "symbol": asset.symbol,
        "network": asset.network.slug,
        "decimals": asset.decimals,
        "accounts": {kind: str(value) for kind, value in sorted(by_type.items())},
        "available": str(by_type.get("customer_available", 0)),
        "reserved": str(by_type.get("withdrawal_reserved", 0)),
        "pending": str(by_type.get("customer_pending", 0)),
    }


@router.get("/projects/{project_id}/balances", response=dict, auth=any_auth)
def project_balances(request, project_id: str, external_customer_id: str | None = None):
    _check_read_scope(request)
    project = resolve_project(request, project_id)
    accounts = list(
        LedgerAccount.objects.select_related("asset", "asset__network")
        .filter(project=project)
        .order_by("asset__symbol")
    )
    if external_customer_id is not None:
        accounts = [
            a for a in accounts if a.external_ref in ("", external_customer_id)
        ]
    grouped: dict[str, dict] = {}
    for account in accounts:
        key = str(account.asset_id)
        grouped.setdefault(key, {"asset": account.asset, "accounts": []})
        grouped[key]["accounts"].append(account)
    items = [_asset_block(g["asset"], g["accounts"]) for g in grouped.values()]
    return {"project_id": str(project.id), "items": items, "total": len(items)}


@router.get("/wallets/{wallet_id}/balances", response=dict, auth=any_auth)
def wallet_balances(request, wallet_id: str):
    _check_read_scope(request)
    wallet = Wallet.objects.select_related("project").filter(id=wallet_id).first()
    if wallet is None:
        raise HttpError(404, "Wallet not found")
    resolve_project(request, str(wallet.project_id))
    accounts = list(
        LedgerAccount.objects.select_related("asset", "asset__network")
        .filter(project=wallet.project, wallet=wallet)
        .order_by("asset__symbol")
    )
    grouped: dict[str, dict] = {}
    for account in accounts:
        key = str(account.asset_id)
        grouped.setdefault(key, {"asset": account.asset, "accounts": []})
        grouped[key]["accounts"].append(account)
    items = [_asset_block(g["asset"], g["accounts"]) for g in grouped.values()]
    return {"wallet_id": str(wallet.id), "items": items, "total": len(items)}
