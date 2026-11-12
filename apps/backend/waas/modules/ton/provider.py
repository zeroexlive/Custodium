"""TON access via the toncenter API (v2 + the v3 lookups the
confirmation path needs).

The two get-methods the platform depends on:

- `seqno` on a wallet contract (send serialisation),
- `get_wallet_address` on a Jetton master — a Jetton wallet
  address can ONLY be derived by executing the master contract;
  there is no offline formula. Results are cached in the database
  by the service layer; this client stays stateless.

Broadcast uses `sendBocReturnHash`: the returned hash is the
external message's cell hash, which is how the confirmation path
later finds the wallet transaction (`transactionsByMessage`).
"""

from __future__ import annotations

import base64

import httpx

from . import addresses
from .cells import Cell, begin_cell
from .chains import TonChain


class TonError(Exception):
    """Base class for TON provider failures."""


class ProviderUnavailable(TonError):
    """Every configured endpoint failed or timed out."""


class BroadcastRejected(TonError):
    """The API refused the external message."""


def _stack_address_arg(raw_address: str) -> str:
    """A runGetMethod stack entry carrying a MsgAddress slice."""
    cell = begin_cell().store_address(raw_address).end_cell()
    return base64.b64encode(cell.to_boc()).decode()


def _parse_stack_address(entry: list) -> str:
    """Read a MsgAddress back out of a ['cell'|'slice', {bytes}]
    stack entry."""
    if not isinstance(entry, list) or len(entry) != 2 or not isinstance(entry[1], dict):
        raise TonError(f"unexpected stack entry: {entry!r}")
    boc = base64.b64decode(entry[1]["bytes"])
    cell = Cell.from_boc(boc)
    raw = cell.begin_parse().read_address()
    if raw is None:
        raise TonError("get-method returned addr_none where an address was required")
    return raw


class TonProvider:
    def __init__(self, chain: TonChain, *, timeout: float = 20.0) -> None:
        if not chain.endpoints:
            raise ValueError("no TON endpoints configured")
        self.chain = chain
        headers = {"Accept": "application/json"}
        if chain.api_key:
            headers["X-API-Key"] = chain.api_key
        self._client = httpx.Client(timeout=timeout, headers=headers, trust_env=False)

    # -- plumbing -----------------------------------------------------
    def _v2(self, method: str, *, params: dict | None = None, post: bool = False) -> object:
        last_error: Exception | None = None
        for base in self.chain.endpoints:
            url = f"{base.rstrip('/')}/{method}"
            try:
                if post:
                    response = self._client.post(url, json=params or {})
                else:
                    response = self._client.get(url, params=params or {})
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                continue
            if not data.get("ok", False):
                raise TonError(f"{method}: {data.get('error') or data.get('code')}")
            return data.get("result")
        raise ProviderUnavailable(f"all TON endpoints failed for {method}: {last_error}")

    def _run_get_method(self, raw_address: str, method: str, stack: list) -> list:
        friendly = addresses.raw_to_friendly(raw_address, bounceable=True)
        result = self._v2(
            "runGetMethod",
            params={"address": friendly, "method": method, "stack": stack},
            post=True,
        )
        if not isinstance(result, dict) or result.get("exit_code") not in (0, None):
            raise TonError(f"get-method {method} failed: {result!r}")
        return result.get("stack", [])  # type: ignore[return-value]

    # -- account state --------------------------------------------------
    def get_account_state(self, raw_address: str) -> str:
        """'active' | 'uninitialized' | 'frozen' | 'nonexist'."""
        friendly = addresses.raw_to_friendly(raw_address, bounceable=True)
        result = self._v2("getAddressInformation", params={"address": friendly})
        if isinstance(result, dict):
            return str(result.get("state", "nonexist"))
        return "nonexist"

    def get_balance(self, raw_address: str) -> int:
        friendly = addresses.raw_to_friendly(raw_address, bounceable=True)
        result = self._v2("getAddressBalance", params={"address": friendly})
        return int(result)  # type: ignore[arg-type]

    def get_seqno(self, raw_address: str) -> int:
        """The wallet contract's current seqno (0 when undeployed)."""
        if self.get_account_state(raw_address) != "active":
            return 0
        stack = self._run_get_method(raw_address, "seqno", [])
        return int(stack[0][1]) if stack else 0

    def get_masterchain_seqno(self) -> int:
        result = self._v2("getMasterchainInfo")
        return int(result["last"]["seqno"])  # type: ignore[index]

    # -- jettons ---------------------------------------------------------
    def get_jetton_wallet_address(self, *, master_raw: str, owner_raw: str) -> str:
        """Execute `get_wallet_address` on the Jetton master."""
        stack = self._run_get_method(
            master_raw, "get_wallet_address", [["slice", _stack_address_arg(owner_raw)]]
        )
        if not stack:
            raise TonError("get_wallet_address returned an empty stack")
        return _parse_stack_address(stack[0])

    # -- transactions -----------------------------------------------------
    def get_transactions(self, raw_address: str, *, limit: int = 50) -> list[dict]:
        friendly = addresses.raw_to_friendly(raw_address, bounceable=True)
        result = self._v2(
            "getTransactions", params={"address": friendly, "limit": limit, "archival": "false"}
        )
        return result if isinstance(result, list) else []

    def find_transaction_by_message(self, message_hash_hex: str) -> dict | None:
        """v3 lookup: the transaction that consumed an (external)
        message, addressed by the message's cell hash."""
        last_error: Exception | None = None
        for base in self.chain.endpoints:
            url = f"{self.chain.v3_base(base)}/transactionsByMessage"
            try:
                response = self._client.get(
                    url,
                    params={
                        "msg_hash": message_hash_hex,
                        "direction": "in",
                    },
                )
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                continue
            transactions = data.get("transactions", []) if isinstance(data, dict) else []
            return transactions[0] if transactions else None
        raise ProviderUnavailable(f"transactionsByMessage failed: {last_error}")

    # -- broadcast ---------------------------------------------------------
    def send_boc_return_hash(self, boc: bytes) -> str:
        """Broadcast an external message; returns its cell hash
        (hex) as reported by the API."""
        try:
            result = self._v2(
                "sendBocReturnHash",
                params={"boc": base64.b64encode(boc).decode()},
                post=True,
            )
        except TonError as exc:
            raise BroadcastRejected(str(exc)) from exc
        if isinstance(result, dict) and result.get("hash"):
            return base64.b64decode(result["hash"]).hex()
        raise BroadcastRejected(f"unexpected sendBocReturnHash result: {result!r}")
