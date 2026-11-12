"""Solana JSON-RPC access.

One POST per call with endpoint failover, mirroring the other
providers (`trust_env=False` — chain traffic only goes to
configured endpoints). RPC-level rejections raise
`TransactionRejected`; transport failures on every endpoint raise
`ProviderUnavailable`.
"""

from __future__ import annotations

import base64

import httpx

from .chains import SolanaChain


class SolanaError(Exception):
    """Base class for Solana provider failures."""


class ProviderUnavailable(SolanaError):
    """Every configured endpoint failed or timed out."""


class TransactionRejected(SolanaError):
    """The RPC node refused the transaction (preflight failure)."""


class SolanaProvider:
    def __init__(self, chain: SolanaChain, *, timeout: float = 20.0) -> None:
        if not chain.endpoints:
            raise ValueError("no Solana RPC endpoints configured")
        self.chain = chain
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            trust_env=False,
        )
        self._request_id = 0

    def _call(self, method: str, params: list) -> object:
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        last_error: Exception | None = None
        for base in self.chain.endpoints:
            try:
                response = self._client.post(base, json=payload)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                continue
            if isinstance(data, dict) and data.get("error"):
                error = data["error"]
                message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                if method == "sendTransaction":
                    raise TransactionRejected(message)
                raise SolanaError(f"{method}: {message}")
            return data.get("result") if isinstance(data, dict) else None
        raise ProviderUnavailable(
            f"all Solana endpoints failed for {method}: {last_error}"
        ) from last_error

    # -- chain state --------------------------------------------------
    def get_slot(self) -> int:
        return int(self._call("getSlot", [{"commitment": "finalized"}]))  # type: ignore[arg-type]

    def get_latest_blockhash(self) -> str:
        result = self._call("getLatestBlockhash", [{"commitment": "finalized"}])
        return str(result["value"]["blockhash"])  # type: ignore[index]

    def get_balance(self, address: str) -> int:
        result = self._call("getBalance", [address])
        return int(result["value"])  # type: ignore[index]

    def get_block(self, slot: int) -> dict | None:
        result = self._call(
            "getBlock",
            [
                slot,
                {
                    "encoding": "jsonParsed",
                    "transactionDetails": "full",
                    "rewards": False,
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        return result if isinstance(result, dict) else None

    def get_signature_status(self, signature: str) -> dict | None:
        result = self._call(
            "getSignatureStatuses", [[signature], {"searchTransactionHistory": True}]
        )
        values = result["value"] if isinstance(result, dict) else []  # type: ignore[index]
        return values[0] if values else None

    # -- broadcast ------------------------------------------------------
    def send_transaction(self, transaction_bytes: bytes) -> str:
        """Broadcast a fully signed transaction; returns its
        signature (the transaction id)."""
        encoded = base64.b64encode(transaction_bytes).decode()
        result = self._call(
            "sendTransaction", [encoded, {"encoding": "base64", "maxRetries": 3}]
        )
        return str(result)
