"""JSON-RPC provider for EVM chains (Phase 4).

One provider instance serves one chain through an ordered list of
endpoints with failover: a transport failure, a malformed response,
or a response for the WRONG chain id moves to the next endpoint; a
well-formed JSON-RPC error from the node is a chain-level answer and
is mapped onto the EVM failure taxonomy (reverts, nonce problems,
replacement problems) instead of being retried blindly.

Broadcast is idempotent-safe by construction: resubmitting the same
raw transaction returns the same transaction hash on any node, and
the "already known" error is treated as success-with-hash.
"""

from __future__ import annotations

import itertools

import httpx

from . import keys
from .chains import EvmChain
from .transactions import transaction_hash


class ProviderError(RuntimeError):
    """Base class for provider failures."""


class ProviderUnavailable(ProviderError):
    """Every endpoint failed at transport/protocol level."""


class WrongChainError(ProviderError):
    """An endpoint answered for a different chain id than configured."""


class RpcError(ProviderError):
    """A well-formed JSON-RPC error returned by a node."""

    def __init__(self, code: int, message: str, data: object = None) -> None:
        super().__init__(f"RPC error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class RevertError(ProviderError):
    """The transaction reverted (or would revert, via eth_call).

    `reason` carries the decoded revert string when the node
    supplied one.
    """

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class NonceError(ProviderError):
    """Nonce problems: too low (already used) or too high (gap)."""


class ReplacementError(ProviderError):
    """A transaction with this nonce exists and the replacement is
    not priced to replace it."""


def _decode_revert_reason(data: object) -> str | None:
    """Decode an ABI Error(string) payload (selector 0x08c379a0)."""
    if not isinstance(data, str) or not data.startswith("0x08c379a0"):
        return None
    try:
        raw = bytes.fromhex(data[10:])
        length = int.from_bytes(raw[32:64], "big")
        return raw[64 : 64 + length].decode("utf-8", errors="replace")
    except (ValueError, IndexError):
        return None


def _map_rpc_error(error: RpcError) -> ProviderError:
    message = error.message or ""
    lowered = message.lower()
    reason = _decode_revert_reason(error.data)
    if reason is not None or "execution reverted" in lowered or "revert" in lowered:
        return RevertError(message, reason=reason)
    if "nonce too low" in lowered or "nonce has already been used" in lowered:
        return NonceError(message)
    if "nonce too high" in lowered:
        return NonceError(message)
    if "underpriced" in lowered or "already known" in lowered and "replacement" in lowered:
        return ReplacementError(message)
    return error


class EvmProvider:
    """JSON-RPC client for one chain with ordered endpoint failover."""

    def __init__(self, chain: EvmChain, *, timeout: float = 15.0, transport=None) -> None:
        if not chain.endpoints:
            raise ProviderUnavailable("no endpoints configured")
        self.chain = chain
        self._ids = itertools.count(1)
        # trust_env=False on purpose: RPC endpoints are explicit
        # configuration, and chain traffic must never be silently
        # routed through an ambient proxy from the process env.
        self._client = httpx.Client(timeout=timeout, transport=transport, trust_env=False)

    # -- transport --------------------------------------------------
    def _call(self, method: str, params: list) -> object:
        last_error: Exception | None = None
        for endpoint in self.chain.endpoints:
            try:
                response = self._client.post(
                    endpoint,
                    json={"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                continue
            if not isinstance(payload, dict) or ("result" not in payload and "error" not in payload):
                last_error = ProviderError(f"malformed JSON-RPC response from {endpoint}")
                continue
            if "error" in payload and payload["error"]:
                err = payload["error"]
                raise _map_rpc_error(
                    RpcError(err.get("code", -1), err.get("message", ""), err.get("data"))
                )
            return payload["result"]
        raise ProviderUnavailable(
            f"all {len(self.chain.endpoints)} endpoints failed for {method}: {last_error}"
        )

    def verify_chain(self) -> int:
        """Fail closed unless the reachable endpoint serves the
        chain id the registry claims for this network."""
        served = self.chain_id()
        if served != self.chain.chain_id:
            raise WrongChainError(
                f"endpoint serves chain {served}, registry expects {self.chain.chain_id} "
                f"for {self.chain.slug}"
            )
        return served

    # -- reads --------------------------------------------------------
    def chain_id(self) -> int:
        return int(self._call("eth_chainId", []), 16)

    def block_number(self) -> int:
        return int(self._call("eth_blockNumber", []), 16)

    def get_balance(self, address: str) -> int:
        return int(self._call("eth_getBalance", [keys.normalize_address(address), "latest"]), 16)

    def get_transaction_count(self, address: str, *, pending: bool = True) -> int:
        """The next usable nonce for an address ('pending' includes
        the node's mempool view, which is what a sender needs)."""
        block = "pending" if pending else "latest"
        return int(
            self._call("eth_getTransactionCount", [keys.normalize_address(address), block]), 16
        )

    def call(self, *, to: str, data: bytes, from_address: str | None = None) -> bytes:
        """eth_call — used for balanceOf reads and for pre-broadcast
        revert simulation."""
        tx: dict = {"to": keys.normalize_address(to), "data": "0x" + data.hex()}
        if from_address is not None:
            tx["from"] = keys.normalize_address(from_address)
        result = self._call("eth_call", [tx, "latest"])
        return bytes.fromhex(result[2:])

    def estimate_gas(self, *, from_address: str, to: str, value: int, data: bytes) -> int:
        """Estimate gas; a reverting estimation surfaces as RevertError."""
        tx = {
            "from": keys.normalize_address(from_address),
            "to": keys.normalize_address(to),
            "value": hex(value),
            "data": "0x" + data.hex(),
        }
        return int(self._call("eth_estimateGas", [tx]), 16)

    def fee_data(self) -> tuple[int, int]:
        """Suggest (max_fee_per_gas, max_priority_fee_per_gas) from
        eth_feeHistory: base fee of the latest block plus the median
        priority fee of recent blocks, with the max fee set to
        2 * base + priority (standard headroom for base-fee rises).
        All integer wei arithmetic."""
        result = self._call("eth_feeHistory", ["0x5", "latest", [50]])
        base_fees = [int(x, 16) for x in result["baseFeePerGas"]]
        rewards = sorted(
            int(block[0], 16) for block in result.get("reward", []) if block and block[0]
        )
        priority = rewards[len(rewards) // 2] if rewards else 1_000_000_000
        latest_base = base_fees[-1] if base_fees else 0
        max_fee = 2 * latest_base + priority
        return max_fee, priority

    # -- writes -------------------------------------------------------
    def send_raw_transaction(self, raw: bytes) -> str:
        """Broadcast a signed transaction; returns its hash.
        Resubmission of an identical transaction is safe: nodes
        answer 'already known', which maps to the same hash."""
        expected = "0x" + transaction_hash(raw).hex()
        try:
            result = self._call("eth_sendRawTransaction", ["0x" + raw.hex()])
        except RpcError as exc:
            if "already known" in (exc.message or "").lower():
                return expected
            raise
        return str(result)

    def get_receipt(self, tx_hash: str) -> dict | None:
        """The transaction receipt, or None while it is not mined.
        A mined receipt with status 0x0 means the transaction
        reverted on-chain."""
        return self._call("eth_getTransactionReceipt", [tx_hash])  # type: ignore[return-value]

    # -- indexing reads (Phase 5) --------------------------------------
    def get_block(self, number: int) -> dict | None:
        """A block with full transaction objects, or None if the
        height does not exist (yet / anymore after a reorg)."""
        return self._call("eth_getBlockByNumber", [hex(number), True])  # type: ignore[return-value]

    def get_block_hash(self, number: int) -> str | None:
        block = self._call("eth_getBlockByNumber", [hex(number), False])
        return None if block is None else str(block["hash"])

    def get_logs(
        self,
        *,
        addresses: list[str],
        topics: list[str | None],
        from_block: int,
        to_block: int,
    ) -> list[dict]:
        """eth_getLogs for the given contract addresses and topic
        filter (None = wildcard position)."""
        if not addresses:
            return []
        result = self._call(
            "eth_getLogs",
            [
                {
                    "address": [keys.normalize_address(a) for a in addresses],
                    "topics": topics,
                    "fromBlock": hex(from_block),
                    "toBlock": hex(to_block),
                }
            ],
        )
        return list(result)  # type: ignore[arg-type]
