"""EVM provider behaviour (Phase 4): failover, chain-id guard, and
the RPC error taxonomy — against httpx mock transports, no network.
"""

from __future__ import annotations

import httpx
import pytest

from waas.modules.evm.chains import EvmChain
from waas.modules.evm.provider import (
    EvmProvider,
    NonceError,
    ProviderUnavailable,
    RevertError,
    WrongChainError,
)
from waas.modules.networks.models import BlockchainNetwork

SEPOLIA = 11155111


def _chain(*endpoints: str) -> EvmChain:
    network = BlockchainNetwork(slug="ethereum-sepolia", chain_id=SEPOLIA)
    return EvmChain(network=network, endpoints=tuple(endpoints))


def _provider(handlers: dict[str, callable]) -> EvmProvider:
    def handle(request: httpx.Request) -> httpx.Response:
        return handlers[request.url.host](request)

    return EvmProvider(
        _chain(*[f"https://{host}" for host in handlers]),
        transport=httpx.MockTransport(handle),
    )


def _rpc_result(value):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})

    return handler


def _rpc_error(code: int, message: str, data: str | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": error})

    return handler


def _by_method(routes: dict[str, callable]):
    import json as jsonlib

    def handler(request: httpx.Request) -> httpx.Response:
        method = jsonlib.loads(request.content)["method"]
        return routes[method](request)

    return handler


def test_failover_to_second_endpoint() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    provider = _provider({"a.example": down, "b.example": _rpc_result("0xaa36a7")})
    assert provider.chain_id() == SEPOLIA


def test_all_endpoints_down() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    provider = _provider({"a.example": down, "b.example": down})
    with pytest.raises(ProviderUnavailable):
        provider.block_number()


def test_wrong_chain_rejected() -> None:
    provider = _provider({"a.example": _rpc_result("0x1")})  # mainnet, not Sepolia
    with pytest.raises(WrongChainError):
        provider.verify_chain()


def test_revert_reason_decoded() -> None:
    # Error(string) payload for "ERC20: transfer amount exceeds balance".
    reason = b"ERC20: transfer amount exceeds balance"
    padding = "00" * ((32 - len(reason) % 32) % 32)
    payload = (
        "0x08c379a0"
        + (32).to_bytes(32, "big").hex()
        + len(reason).to_bytes(32, "big").hex()
        + reason.hex()
        + padding
    )
    provider = _provider(
        {
            "a.example": _by_method(
                {
                    "eth_chainId": _rpc_result("0xaa36a7"),
                    "eth_call": _rpc_error(3, "execution reverted", payload),
                }
            )
        }
    )
    provider.verify_chain()
    with pytest.raises(RevertError) as excinfo:
        provider.call(to="0x" + "11" * 20, data=b"\x70\xa0\x82\x31")
    assert excinfo.value.reason == "ERC20: transfer amount exceeds balance"


def test_nonce_error_mapped() -> None:
    provider = _provider({"a.example": _rpc_error(-32000, "nonce too low")})
    with pytest.raises(NonceError):
        provider.get_transaction_count("0x" + "11" * 20)


def test_fee_data_math() -> None:
    fee_history = {
        "baseFeePerGas": ["0x64", "0xc8", "0x12c"],  # 100, 200, 300 (last = next block)
        "reward": [["0x3b9aca00"], ["0x77359400"], ["0x59682f00"]],  # 1, 2, 1.5 gwei
    }
    provider = _provider(
        {"a.example": _by_method({"eth_feeHistory": _rpc_result(fee_history)})}
    )
    max_fee, priority = provider.fee_data()
    assert priority == 1_500_000_000  # median
    assert max_fee == 2 * 300 + 1_500_000_000


def test_already_known_broadcast_is_idempotent() -> None:
    provider = _provider({"a.example": _rpc_error(-32000, "already known")})
    raw = bytes.fromhex("02deadbeef")
    result = provider.send_raw_transaction(raw)
    from waas.modules.evm.transactions import transaction_hash

    assert result == "0x" + transaction_hash(raw).hex()
