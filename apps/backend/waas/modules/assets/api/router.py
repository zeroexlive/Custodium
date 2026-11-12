from __future__ import annotations

from ninja import Router, Schema, Status
from ninja.errors import HttpError

from waas.api.authentication import AnyAuth, DashboardAuth
from waas.common.pagination import paginated
from waas.modules.assets.models import Asset
from waas.modules.networks.models import BlockchainNetwork

router = Router(tags=["assets"])
any_auth = AnyAuth()
dashboard_auth = DashboardAuth()


def asset_out(asset: Asset) -> dict:
    return {
        "id": str(asset.id),
        "network": asset.network.slug,
        "symbol": asset.symbol,
        "name": asset.name,
        "decimals": asset.decimals,
        "token_standard": asset.token_standard,
        "contract_or_mint_address": asset.contract_or_mint_address,
        "token_program": asset.token_program or None,
        "issuer_classification": asset.issuer_classification,
        "verification_status": asset.verification_status,
        "deposit_enabled": asset.deposit_enabled,
        "withdrawal_enabled": asset.withdrawal_enabled,
        "operational_status": asset.operational_status,
    }


class AssetIn(Schema):
    network: str  # network slug
    symbol: str
    name: str
    decimals: int
    token_standard: str
    contract_or_mint_address: str | None = None
    token_program: str = ""
    issuer_classification: str = "unknown"


@router.get("/assets", response=dict, auth=any_auth)
def list_assets(request, network: str | None = None):
    assets = Asset.objects.select_related("network").all()
    if network:
        assets = assets.filter(network__slug=network)
    return paginated(asset_out(a) for a in assets)


@router.get("/assets/{asset_id}", response=dict, auth=any_auth)
def get_asset(request, asset_id: str):
    asset = Asset.objects.select_related("network").filter(id=asset_id).first()
    if asset is None:
        raise HttpError(404, "Asset not found")
    return asset_out(asset)


@router.post("/assets", response={201: dict}, auth=dashboard_auth)
def create_asset(request, payload: AssetIn):
    """Platform-admin only in Phase 1/2: asset registration is a privileged
    operation (verification workflow arrives with the admin experience)."""
    if not request.auth.is_staff:
        raise HttpError(403, "Asset registration requires a platform administrator")
    network = BlockchainNetwork.objects.filter(slug=payload.network).first()
    if network is None:
        raise HttpError(422, f"Unknown network: {payload.network}")
    if payload.decimals < 0 or payload.decimals > 36:
        raise HttpError(422, "decimals out of range")
    asset = Asset.objects.create(
        network=network, symbol=payload.symbol.upper(), name=payload.name,
        decimals=payload.decimals, token_standard=payload.token_standard,
        contract_or_mint_address=payload.contract_or_mint_address,
        token_program=payload.token_program,
        issuer_classification=payload.issuer_classification,
        verification_status=Asset.VerificationStatus.UNVERIFIED,
    )
    return Status(201, asset_out(asset))
