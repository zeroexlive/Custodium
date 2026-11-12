"""Minimal protobuf wire encoding — only what TRON transaction
construction needs.

Field numbers were verified against the official protocol
definitions (tronprotocol/protocol: core/Tron.proto,
core/contract/balance_contract.proto,
core/contract/smart_contract.proto) on 2026-11-12:

- Transaction:            raw_data = 1, signature = 2
- Transaction.raw:        ref_block_bytes = 1, ref_block_num = 3,
                          ref_block_hash = 4, expiration = 8,
                          data = 10, contract = 11,
                          timestamp = 14, fee_limit = 18
- Transaction.Contract:   type = 1, parameter = 2 (Any)
- google.protobuf.Any:    type_url = 1, value = 2
- TransferContract:       owner_address = 1, to_address = 2,
                          amount = 3            (type enum 1)
- TriggerSmartContract:   owner_address = 1, contract_address = 2,
                          call_value = 3, data = 4,
                          call_token_value = 5, token_id = 6
                                              (type enum 31)

Encoding follows canonical protobuf rules: fields in ascending
field-number order, proto3 zero values omitted.
"""

from __future__ import annotations


def varint(value: int) -> bytes:
    if value < 0:
        # int64 negative values encode as 10-byte two's complement.
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def tag(field_number: int, wire_type: int) -> bytes:
    return varint((field_number << 3) | wire_type)


def field_varint(field_number: int, value: int) -> bytes:
    if value == 0:
        return b""  # proto3 default omission
    return tag(field_number, 0) + varint(value)


def field_bytes(field_number: int, payload: bytes) -> bytes:
    if not payload:
        return b""  # proto3 default omission
    return tag(field_number, 2) + varint(len(payload)) + payload


def any_message(type_url: str, value: bytes) -> bytes:
    """google.protobuf.Any wrapping a serialized message."""
    return field_bytes(1, type_url.encode()) + field_bytes(2, value)
