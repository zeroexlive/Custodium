"""TRON unit tests: Base58Check address vectors (the Phase 2 USDT
pair), key→address derivation, and protobuf transaction encoding
checked against hand-assembled golden bytes built directly from
the official protocol field numbers.
"""

from __future__ import annotations

import hashlib

import pytest

from waas.modules.evm import keys
from waas.modules.tron import addresses
from waas.modules.tron import protobuf as pb
from waas.modules.tron import transactions as tron_tx

USDT_HEX = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"
USDT_B58 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
OWNER = "41" + "aa" * 20
RECIPIENT = "41" + "bb" * 20
BLOCK_ID = "0000000000000001" + "1122334455667788" + "99" * 16


def test_usdt_address_pair_both_directions() -> None:
    assert addresses.hex_to_base58(USDT_HEX) == USDT_B58
    assert addresses.base58_to_hex(USDT_B58) == USDT_HEX
    assert addresses.normalize_to_hex(USDT_B58) == USDT_HEX
    assert addresses.normalize_to_hex(USDT_HEX.upper()) == USDT_HEX


def test_base58check_rejects_bad_checksum() -> None:
    with pytest.raises(addresses.TronAddressError):
        addresses.base58_to_hex(USDT_B58[:-1] + "u")
    assert addresses.is_valid(USDT_B58)
    assert not addresses.is_valid("TnotAnAddress")


def test_address_from_test_key_round_trips() -> None:
    # TEST-ONLY key handling via the cryptography library (the same
    # published 0x4646… test key the Phase 4 pipeline tests use).
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.derive_private_key(int.from_bytes(bytes.fromhex("46" * 32), "big"), ec.SECP256K1())
    numbers = key.public_key().public_numbers()
    public = numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    b58 = addresses.address_from_public_key(public)
    assert b58.startswith("T")
    assert addresses.base58_to_hex(b58) == addresses.hex_from_public_key(public)
    # The same key material yields the known EVM address for 0x4646…
    assert keys.address_from_public_key(public) == "0x9d8A62f656a8d1615C1294fd71e9CFb3E4855A4F"
    # …and the TRON hex form is the 0x41-prefixed lowercase body.
    assert addresses.hex_from_public_key(public) == "419d8a62f656a8d1615c1294fd71e9cfb3e4855a4f"


def test_varint_vectors() -> None:
    assert pb.varint(0) == b"\x00"
    assert pb.varint(1) == b"\x01"
    assert pb.varint(300) == b"\xac\x02"
    assert pb.varint(1_000_000) == bytes([0xC0, 0x84, 0x3D])


def _golden_raw_transfer() -> bytes:
    """Hand-assembled from the protocol field numbers — independent
    of the implementation under test."""
    owner = bytes.fromhex(OWNER)
    to = bytes.fromhex(RECIPIENT)
    # TransferContract: owner=1 (bytes), to=2 (bytes), amount=3 (varint)
    transfer = (
        b"\x0a\x15" + owner
        + b"\x12\x15" + to
        + b"\x18" + bytes([0xC0, 0x84, 0x3D])  # 1_000_000
    )
    url = b"type.googleapis.com/protocol.TransferContract"
    any_msg = b"\x0a" + bytes([len(url)]) + url + b"\x12" + bytes([len(transfer)]) + transfer
    # Contract: type=1 (varint 1), parameter=2 (Any)
    contract = b"\x08\x01" + b"\x12" + bytes([len(any_msg)]) + any_msg
    raw = (
        b"\x0a\x02\x03\xe8"  # ref_block_bytes field 1: block 1000 & 0xFFFF
        + b"\x18\xe8\x07"  # ref_block_num field 3: 1000
        + b"\x22\x08" + bytes.fromhex("1122334455667788")  # ref_block_hash field 4
        + b"\x40" + pb.varint(1_700_000_060_000)  # expiration field 8
        + b"\x5a" + bytes([len(contract)]) + contract  # contract field 11
        + b"\x70" + pb.varint(1_700_000_000_000)  # timestamp field 14
    )
    return raw


def test_native_transfer_matches_golden_bytes() -> None:
    built = tron_tx.build_native_transfer(
        owner_hex=OWNER,
        to_hex=RECIPIENT,
        amount_sun=1_000_000,
        ref_block_number=1000,
        ref_block_id=BLOCK_ID,
        timestamp_ms=1_700_000_000_000,
        expiration_ms=1_700_000_060_000,
    )
    golden = _golden_raw_transfer()
    assert built.raw_data_bytes() == golden
    assert built.tx_id() == hashlib.sha256(golden).hexdigest()
    # Deterministic: identical inputs -> identical bytes/id.
    again = tron_tx.build_native_transfer(
        owner_hex=OWNER, to_hex=RECIPIENT, amount_sun=1_000_000,
        ref_block_number=1000, ref_block_id=BLOCK_ID,
        timestamp_ms=1_700_000_000_000, expiration_ms=1_700_000_060_000,
    )
    assert again.raw_data_bytes() == golden


def test_token_transfer_structure() -> None:
    built = tron_tx.build_token_transfer(
        owner_hex=OWNER,
        contract_hex=USDT_HEX,
        to_hex=RECIPIENT,
        amount=250_000_000,
        ref_block_number=1000,
        ref_block_id=BLOCK_ID,
        timestamp_ms=1_700_000_000_000,
    )
    raw = built.raw_data_bytes()
    # TriggerSmartContract type enum 31 inside the Contract message.
    assert b"\x08\x1f" in raw
    # ABI payload: transfer selector + padded 20-byte recipient + amount.
    payload = built.parameter_json["data"]
    assert payload.startswith("a9059cbb")
    assert payload[8:72] == "00" * 12 + "bb" * 20
    assert int(payload[72:], 16) == 250_000_000
    assert built.fee_limit_sun == tron_tx.DEFAULT_FEE_LIMIT_SUN
    # fee_limit is raw field 18 (tag 0x90 0x01).
    assert b"\x90\x01" in raw
    assert built.broadcast_json(b"\x11" * 65)["signature"] == ["11" * 65]
