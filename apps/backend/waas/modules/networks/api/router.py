from __future__ import annotations

from ninja import Router

from waas.api.authentication import AnyAuth
from waas.common.pagination import paginated
from waas.modules.networks.models import BlockchainNetwork

router = Router(tags=["networks"])
any_auth = AnyAuth()


def network_out(network: BlockchainNetwork) -> dict:
    return {
        "id": str(network.id),
        "slug": network.slug,
        "name": network.name,
        "native_symbol": network.native_symbol,
        "native_decimals": network.native_decimals,
        "signature_family": network.signature_family,
        "is_testnet": network.is_testnet,
        "operational_status": network.operational_status,
        "chain_id": network.chain_id,
    }


@router.get("/networks", response=dict, auth=any_auth)
def list_networks(request):
    return paginated(network_out(n) for n in BlockchainNetwork.objects.all())
