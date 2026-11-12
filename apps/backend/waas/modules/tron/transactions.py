"""TRON transaction construction (TRX TransferContract and TRC-20
TriggerSmartContract) with deterministic protobuf serialization.

The transaction id is ``sha256(raw_data protobuf bytes)`` — the
exact digest the signer port signs. There is no private-key
material here; signatures arrive from the signing port and are
attached as opaque 65-byte values (r ‖ s ‖ recovery-id).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from waas.modules.evm import transactions as evm_tx

from . import addresses
from . import protobuf as pb

TRANSFER_CONTRACT_TYPE = 1
TRIGGER_SMART_CONTRACT_TYPE = 31
_TYPE_URLS = {
    TRANSFER_CONTRACT_TYPE: "type.googleapis.com/protocol.TransferContract",
    TRIGGER_SMART_CONTRACT_TYPE: "type.googleapis.com/protocol.TriggerSmartContract",
}
# TRC-20 transfer fee limit: 15 TRX in SUN. Generous for a plain
# transfer; the unused portion is not consumed. Native TRX
# transfers need no fee limit (bandwidth is the resource).
DEFAULT_FEE_LIMIT_SUN = 15_000_000
DEFAULT_EXPIRATION_MS = 3_600_000  # 1 hour: MPC ceremonies are slow


@dataclass(frozen=True)
class TronTransaction:
    """A fully-specified unsigned TRON transaction."""

    contract_type: int
    contract_parameter: bytes  # serialized contract message
    parameter_json: dict  # the contract parameter's JSON (hex) form
    ref_block_bytes: bytes  # 2 bytes: block number low bits, big-endian
    ref_block_num: int
    ref_block_hash: bytes  # 8 bytes: block id bytes 8..16
    timestamp_ms: int
    expiration_ms: int
    fee_limit_sun: int = 0

    def raw_data_bytes(self) -> bytes:
        contract = pb.field_varint(1, self.contract_type) + pb.field_bytes(
            2, pb.any_message(_TYPE_URLS[self.contract_type], self.contract_parameter)
        )
        return b"".join(
            [
                pb.field_bytes(1, self.ref_block_bytes),
                pb.field_varint(3, self.ref_block_num),
                pb.field_bytes(4, self.ref_block_hash),
                pb.field_varint(8, self.expiration_ms),
                pb.field_bytes(11, contract),
                pb.field_varint(14, self.timestamp_ms),
                pb.field_varint(18, self.fee_limit_sun),
            ]
        )

    def tx_id(self) -> str:
        return hashlib.sha256(self.raw_data_bytes()).hexdigest()

    def signing_digest(self) -> bytes:
        return bytes.fromhex(self.tx_id())

    def raw_data_json(self) -> dict:
        contract_type_name = (
            "TransferContract"
            if self.contract_type == TRANSFER_CONTRACT_TYPE
            else "TriggerSmartContract"
        )
        return {
            "ref_block_bytes": self.ref_block_bytes.hex(),
            "ref_block_num": self.ref_block_num,
            "ref_block_hash": self.ref_block_hash.hex(),
            "expiration": self.expiration_ms,
            "timestamp": self.timestamp_ms,
            "contract": [
                {"parameter": {"value": self.parameter_json, "type_url": _TYPE_URLS[self.contract_type]},
                 "type": contract_type_name}
            ],
            **({"fee_limit": self.fee_limit_sun} if self.fee_limit_sun else {}),
        }

    def broadcast_json(self, signature: bytes) -> dict:
        """The full transaction object for /wallet/broadcasttransaction."""
        if len(signature) != 65:
            raise ValueError("TRON signature must be 65 bytes (r || s || v)")
        return {
            "visible": False,
            "txID": self.tx_id(),
            "raw_data": self.raw_data_json(),
            "raw_data_hex": self.raw_data_bytes().hex(),
            "signature": [signature.hex()],
        }


def _ref_block_parts(block_number: int, block_id_hex: str) -> tuple[bytes, bytes]:
    block_id = bytes.fromhex(block_id_hex)
    if len(block_id) != 32:
        raise ValueError("block id must be 32 bytes")
    return (block_number & 0xFFFF).to_bytes(2, "big"), block_id[8:16]


def build_native_transfer(
    *,
    owner_hex: str,
    to_hex: str,
    amount_sun: int,
    ref_block_number: int,
    ref_block_id: str,
    timestamp_ms: int,
    expiration_ms: int | None = None,
) -> TronTransaction:
    """A TRX TransferContract. Addresses are ``41…`` hex form."""
    if amount_sun <= 0:
        raise ValueError("amount must be positive")
    owner = bytes.fromhex(addresses.normalize_to_hex(owner_hex))
    to = bytes.fromhex(addresses.normalize_to_hex(to_hex))
    parameter = (
        pb.field_bytes(1, owner) + pb.field_bytes(2, to) + pb.field_varint(3, amount_sun)
    )
    ref_bytes, ref_hash = _ref_block_parts(ref_block_number, ref_block_id)
    return TronTransaction(
        contract_type=TRANSFER_CONTRACT_TYPE,
        contract_parameter=parameter,
        parameter_json={
            "owner_address": owner.hex(),
            "to_address": to.hex(),
            "amount": amount_sun,
        },
        ref_block_bytes=ref_bytes,
        ref_block_num=ref_block_number,
        ref_block_hash=ref_hash,
        timestamp_ms=timestamp_ms,
        expiration_ms=expiration_ms or timestamp_ms + DEFAULT_EXPIRATION_MS,
    )


def build_token_transfer(
    *,
    owner_hex: str,
    contract_hex: str,
    to_hex: str,
    amount: int,
    ref_block_number: int,
    ref_block_id: str,
    timestamp_ms: int,
    expiration_ms: int | None = None,
    fee_limit_sun: int = DEFAULT_FEE_LIMIT_SUN,
) -> TronTransaction:
    """A TRC-20 ``transfer(address,uint256)`` TriggerSmartContract.
    The token is identified by its contract address, never symbol.
    The ABI payload is identical to the EVM encoding (TRON adopted
    the Ethereum ABI for TRC-20)."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    owner = bytes.fromhex(addresses.normalize_to_hex(owner_hex))
    contract = bytes.fromhex(addresses.normalize_to_hex(contract_hex))
    # TRC-20 takes the 20-byte account body (no 0x41 prefix) in ABI.
    to_body = bytes.fromhex(addresses.normalize_to_hex(to_hex))[1:]
    data = evm_tx.erc20_transfer_data(to_address="0x" + to_body.hex(), amount=amount)
    parameter = (
        pb.field_bytes(1, owner)
        + pb.field_bytes(2, contract)
        + pb.field_bytes(4, data)
    )
    ref_bytes, ref_hash = _ref_block_parts(ref_block_number, ref_block_id)
    return TronTransaction(
        contract_type=TRIGGER_SMART_CONTRACT_TYPE,
        contract_parameter=parameter,
        parameter_json={
            "owner_address": owner.hex(),
            "contract_address": contract.hex(),
            "data": data.hex(),
        },
        ref_block_bytes=ref_bytes,
        ref_block_num=ref_block_number,
        ref_block_hash=ref_hash,
        timestamp_ms=timestamp_ms,
        expiration_ms=expiration_ms or timestamp_ms + DEFAULT_EXPIRATION_MS,
        fee_limit_sun=fee_limit_sun,
    )
