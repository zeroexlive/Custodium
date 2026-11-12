"""TRON node access over the TronGrid-style HTTP API.

POST-only JSON endpoints under ``/wallet/…``. The client fails over
across the configured endpoints in order; every call either returns
the node's JSON or raises `ProviderUnavailable`. Broadcast
rejections raise `BroadcastRejected` with the node's code/message;
"duplicate transaction" style responses for an already-known txID
resolve to the txID itself — broadcast is idempotent by txID.

Like the EVM provider, the HTTP client ignores ambient proxy
environment variables (`trust_env=False`): chain traffic only ever
goes to configured endpoints. An optional API key
(`settings.TRON_API_KEY`) is sent as the `TRON-PRO-API-KEY`
header.
"""

from __future__ import annotations

import httpx
from django.conf import settings

from .chains import TronChain


class TronError(Exception):
    """Base class for TRON provider failures."""


class ProviderUnavailable(TronError):
    """Every configured endpoint failed or timed out."""


class BroadcastRejected(TronError):
    """The node refused the transaction (validation failed)."""


class TronProvider:
    def __init__(self, chain: TronChain, *, timeout: float = 20.0) -> None:
        if not chain.endpoints:
            raise ValueError("no TRON API endpoints configured")
        self.chain = chain
        headers = {"Accept": "application/json"}
        api_key = getattr(settings, "TRON_API_KEY", "") or ""
        if api_key:
            headers["TRON-PRO-API-KEY"] = api_key
        self._client = httpx.Client(
            timeout=timeout, headers=headers, trust_env=False
        )

    def _post(self, path: str, payload: dict) -> dict:
        last_error: Exception | None = None
        for base in self.chain.endpoints:
            try:
                response = self._client.post(f"{base}{path}", json=payload)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ProviderUnavailable(f"unexpected response from {base}{path}")
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
        raise ProviderUnavailable(
            f"all TRON endpoints failed for {path}: {last_error}"
        ) from last_error

    # -- chain state --------------------------------------------------
    def now_block(self) -> dict:
        """The current head block: {number, block_id, timestamp_ms}."""
        block = self._post("/wallet/getnowblock", {})
        header = block.get("block_header", {}).get("raw_data", {})
        return {
            "number": int(header.get("number", 0)),
            "block_id": str(block.get("blockID", "")),
            "timestamp_ms": int(header.get("timestamp", 0)),
        }

    def get_block(self, number: int) -> dict | None:
        block = self._post("/wallet/getblockbynum", {"num": number})
        if not block or "block_header" not in block:
            return None
        return block

    def get_block_id(self, number: int) -> str | None:
        block = self.get_block(number)
        return None if block is None else str(block.get("blockID", ""))

    def head_number(self) -> int:
        return self.now_block()["number"]

    # -- accounts / transactions --------------------------------------
    def get_account(self, address_hex: str) -> dict:
        return self._post(
            "/wallet/getaccount", {"address": address_hex, "visible": False}
        )

    def get_transaction_info(self, tx_id: str) -> dict | None:
        info = self._post("/wallet/gettransactioninfobyid", {"value": tx_id})
        if not info or "id" not in info:
            return None
        return info

    def broadcast(self, tx_json: dict) -> str:
        """Broadcast a signed transaction; returns the txID.
        Re-broadcasting a known transaction resolves to its txID."""
        result = self._post("/wallet/broadcasttransaction", tx_json)
        if result.get("result") is True:
            return str(tx_json["txID"])
        code = str(result.get("code", ""))
        message = result.get("message", "")
        if isinstance(message, str):
            try:
                message = bytes.fromhex(message).decode(errors="replace")
            except ValueError:
                pass
        if "DUP" in code.upper() or "duplicate" in str(message).lower():
            return str(tx_json["txID"])
        raise BroadcastRejected(f"{code}: {message}")
