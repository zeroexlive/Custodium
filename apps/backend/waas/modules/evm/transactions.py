"""EVM transaction construction (Phase 4): EIP-1559 (type 2) and
legacy (EIP-155) transfers — native currency and generic
ERC-20/BEP-20 `transfer` — plus signing-hash computation, signed
transaction assembly from an externally produced signature, and
parsing.

This module never signs anything itself and never sees a private
key: signing produces a Keccak-256 digest here; the signature is
made elsewhere (the MPC ceremony) and comes back as (r, s), from
which the recovery id is resolved against the known public key
(see `keys.find_recovery_id`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import keys, rlp

# ERC-20/BEP-20 transfer(address,uint256) selector: first 4 bytes of
# Keccak-256 of the canonical signature.
ERC20_TRANSFER_SELECTOR = keys.keccak256(b"transfer(address,uint256)")[:4]


def erc20_transfer_data(to_address: str, amount: int) -> bytes:
    """ABI-encode an ERC-20/BEP-20 transfer call."""
    if amount < 0:
        raise ValueError("amount must be non-negative")
    recipient = bytes.fromhex(keys.normalize_address(to_address)[2:])
    return (
        ERC20_TRANSFER_SELECTOR
        + recipient.rjust(32, b"\x00")
        + amount.to_bytes(32, "big")
    )


def erc20_balance_of_data(owner_address: str) -> bytes:
    """ABI-encode a balanceOf(address) call."""
    selector = keys.keccak256(b"balanceOf(address)")[:4]
    owner = bytes.fromhex(keys.normalize_address(owner_address)[2:])
    return selector + owner.rjust(32, b"\x00")


@dataclass(frozen=True)
class UnsignedTransaction:
    """A fully-specified unsigned EVM transaction."""

    chain_id: int
    nonce: int
    to: str  # checksummed or lowercase address; contract creation unsupported
    value: int  # wei, >= 0
    data: bytes = b""
    gas_limit: int = 21_000
    # EIP-1559 fields (type 2). If max_fee_per_gas is None the
    # transaction is legacy and gas_price is used instead.
    max_fee_per_gas: int | None = None
    max_priority_fee_per_gas: int | None = None
    gas_price: int | None = None
    access_list: list = field(default_factory=list)

    def __post_init__(self) -> None:
        keys.normalize_address(self.to)
        if self.value < 0 or self.nonce < 0 or self.gas_limit <= 0:
            raise ValueError("invalid transaction numeric field")
        if self.is_type2:
            if self.max_fee_per_gas is None or self.max_priority_fee_per_gas is None:
                raise ValueError("type-2 transactions need both fee fields")
            if self.max_priority_fee_per_gas > self.max_fee_per_gas:
                raise ValueError("priority fee exceeds max fee")
        elif self.gas_price is None:
            raise ValueError("legacy transactions need gas_price")

    @property
    def is_type2(self) -> bool:
        return self.max_fee_per_gas is not None or self.gas_price is None

    def signing_payload(self) -> bytes:
        """The exact bytes that are Keccak-hashed for signing."""
        to_bytes = bytes.fromhex(self.to[2:])
        if self.is_type2:
            return b"\x02" + rlp.encode(
                [
                    self.chain_id,
                    self.nonce,
                    self.max_priority_fee_per_gas,
                    self.max_fee_per_gas,
                    self.gas_limit,
                    to_bytes,
                    self.value,
                    self.data,
                    self.access_list,
                ]
            )
        # Legacy EIP-155: chain id + two empty fields in place of v/r/s.
        return rlp.encode(
            [
                self.nonce,
                self.gas_price,
                self.gas_limit,
                to_bytes,
                self.value,
                self.data,
                self.chain_id,
                0,
                0,
            ]
        )

    def sighash(self) -> bytes:
        return keys.keccak256(self.signing_payload())

    def assemble_signed(self, r: int, s: int, recovery_id: int) -> bytes:
        """Assemble the raw signed transaction from an external
        signature. The caller is responsible for deriving
        `recovery_id` (see keys.find_recovery_id)."""
        if recovery_id not in (0, 1):
            raise ValueError("recovery_id must be 0 or 1")
        to_bytes = bytes.fromhex(self.to[2:])
        if self.is_type2:
            return b"\x02" + rlp.encode(
                [
                    self.chain_id,
                    self.nonce,
                    self.max_priority_fee_per_gas,
                    self.max_fee_per_gas,
                    self.gas_limit,
                    to_bytes,
                    self.value,
                    self.data,
                    self.access_list,
                    recovery_id,
                    r,
                    s,
                ]
            )
        v = self.chain_id * 2 + 35 + recovery_id  # EIP-155
        return rlp.encode(
            [
                self.nonce,
                self.gas_price,
                self.gas_limit,
                to_bytes,
                self.value,
                self.data,
                v,
                r,
                s,
            ]
        )


def build_native_transfer(
    *,
    chain_id: int,
    nonce: int,
    to: str,
    amount_wei: int,
    gas_limit: int = 21_000,
    max_fee_per_gas: int | None = None,
    max_priority_fee_per_gas: int | None = None,
    gas_price: int | None = None,
) -> UnsignedTransaction:
    return UnsignedTransaction(
        chain_id=chain_id,
        nonce=nonce,
        to=keys.normalize_address(to),
        value=amount_wei,
        data=b"",
        gas_limit=gas_limit,
        max_fee_per_gas=max_fee_per_gas,
        max_priority_fee_per_gas=max_priority_fee_per_gas,
        gas_price=gas_price,
    )


def build_token_transfer(
    *,
    chain_id: int,
    nonce: int,
    token_contract: str,
    to: str,
    amount: int,
    gas_limit: int = 65_000,
    max_fee_per_gas: int | None = None,
    max_priority_fee_per_gas: int | None = None,
    gas_price: int | None = None,
) -> UnsignedTransaction:
    """A transfer of an arbitrary ERC-20/BEP-20 token: the token is
    identified by its contract address (never by symbol), the value
    carried by the transaction itself is 0, and the amount is in the
    token's base units."""
    return UnsignedTransaction(
        chain_id=chain_id,
        nonce=nonce,
        to=keys.normalize_address(token_contract),
        value=0,
        data=erc20_transfer_data(to, amount),
        gas_limit=gas_limit,
        max_fee_per_gas=max_fee_per_gas,
        max_priority_fee_per_gas=max_priority_fee_per_gas,
        gas_price=gas_price,
    )


def transaction_hash(raw_signed: bytes) -> bytes:
    """The chain-facing transaction id: Keccak-256 of the raw tx."""
    return keys.keccak256(raw_signed)
