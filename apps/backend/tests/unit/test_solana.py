"""Solana unit tests: base58/shortvec vectors, Ed25519 on-curve
edge cases with exact known encodings, PDA/ATA properties, legacy
message compilation (parsed back byte-by-byte), and real Ed25519
signature verification over compiled messages (test keys only,
via the cryptography library).
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from waas.modules.solana import base58, keys
from waas.modules.solana import transactions as sol_tx

# Ed25519 base point compressed (y = 4/5): the canonical generator encoding.
BASE_POINT = bytes.fromhex(
    "5866666666666666666666666666666666666666666666666666666666666666"
)
# y = p - 1 (the order-2 point (0, -1)): x^2 = 0.
Y_MINUS_ONE_SIGN0 = (2**255 - 20).to_bytes(32, "little")
Y_MINUS_ONE_SIGN1 = bytearray(Y_MINUS_ONE_SIGN0)
Y_MINUS_ONE_SIGN1[31] |= 0x80


def test_base58_vectors() -> None:
    assert base58.encode(bytes(32)) == "11111111111111111111111111111111"
    assert base58.decode("11111111111111111111111111111111") == bytes(32)
    assert keys.SYSTEM_PROGRAM == base58.encode(bytes(32))
    raw = bytes(range(32))
    assert base58.decode(base58.encode(raw)) == raw
    with pytest.raises(base58.Base58Error):
        base58.decode("0OIl")  # excluded characters


def test_shortvec_vectors() -> None:
    assert sol_tx.shortvec(0) == b"\x00"
    assert sol_tx.shortvec(1) == b"\x01"
    assert sol_tx.shortvec(127) == b"\x7f"
    assert sol_tx.shortvec(128) == b"\x80\x01"
    assert sol_tx.shortvec(300) == b"\xac\x02"
    assert sol_tx.shortvec(16383) == b"\xff\x7f"
    assert sol_tx.shortvec(16384) == b"\x80\x80\x01"


def test_on_curve_known_points() -> None:
    assert keys.is_on_curve(BASE_POINT) is True
    assert keys.is_on_curve(bytes(Y_MINUS_ONE_SIGN0)) is True  # x == 0, sign 0
    # x == 0 with the sign bit set is not a valid decompression.
    assert keys.is_on_curve(bytes(Y_MINUS_ONE_SIGN1)) is False
    # y >= p is invalid.
    assert keys.is_on_curve((2**255 - 19).to_bytes(32, "little")) is False


def test_ata_derivation_properties() -> None:
    owner = keys.address_from_public_key(bytes(range(32)))
    mint = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"  # USDT
    ata = keys.associated_token_address(owner=owner, mint=mint)
    # Deterministic, off-curve (no private key exists), owner/mint-sensitive.
    assert ata == keys.associated_token_address(owner=owner, mint=mint)
    assert keys.is_on_curve(base58.decode(ata)) is False
    other_owner = keys.address_from_public_key(bytes(range(32, 64)))
    assert keys.associated_token_address(owner=other_owner, mint=mint) != ata


def _parse_message(message: bytes) -> dict:
    """Minimal legacy-message parser for test assertions."""
    header = list(message[:3])
    pos = 3

    def read_shortvec() -> int:
        nonlocal pos
        value, shift = 0, 0
        while True:
            byte = message[pos]
            pos += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7

    count = read_shortvec()
    account_keys = [message[pos + 32 * i : pos + 32 * (i + 1)] for i in range(count)]
    pos += 32 * count
    blockhash = message[pos : pos + 32]
    pos += 32
    instructions = []
    for _ in range(read_shortvec()):
        program_index = message[pos]
        pos += 1
        accounts = [message[pos + j] for j in range(read_shortvec())]
        pos += len(accounts)
        data_len = read_shortvec()
        data = message[pos : pos + data_len]
        pos += data_len
        instructions.append(
            {"program": program_index, "accounts": accounts, "data": data}
        )
    assert pos == len(message)
    return {"header": header, "keys": account_keys, "blockhash": blockhash, "instructions": instructions}


def test_system_transfer_compilation() -> None:
    payer = bytes(range(32))
    recipient = bytes(range(32, 64))
    blockhash = bytes([7] * 32)
    instruction = sol_tx.system_transfer(
        from_pubkey=payer, to_pubkey=recipient, lamports=500_000_000
    )
    compiled = sol_tx.compile_message(
        fee_payer=payer, instructions=[instruction], recent_blockhash=blockhash
    )
    parsed = _parse_message(compiled.message_bytes)
    # 1 signer (payer, writable); SystemProgram is the only readonly
    # unsigned account; recipient writable unsigned.
    assert parsed["header"] == [1, 0, 1]
    assert parsed["keys"][0] == payer
    assert parsed["keys"][1] == recipient
    assert parsed["keys"][2] == bytes(32)  # SystemProgram
    ix = parsed["instructions"][0]
    assert ix["program"] == 2
    assert ix["accounts"] == [0, 1]
    assert ix["data"][:4] == (2).to_bytes(4, "little")
    assert int.from_bytes(ix["data"][4:], "little") == 500_000_000
    assert compiled.signer_keys == [payer]


def test_compiled_message_signs_and_verifies() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    public = private.public_key().public_bytes_raw()
    recipient = bytes(range(32, 64))
    compiled = sol_tx.compile_message(
        fee_payer=public,
        instructions=[
            sol_tx.system_transfer(from_pubkey=public, to_pubkey=recipient, lamports=1)
        ],
        recent_blockhash=bytes([9] * 32),
    )
    signature = private.sign(compiled.message_bytes)
    # Standard Ed25519 verification (what the chain performs).
    private.public_key().verify(signature, compiled.message_bytes)
    wire = sol_tx.assemble_transaction(compiled.message_bytes, [signature])
    assert wire[0] == 1
    assert wire[1:65] == signature
    assert wire[65:] == compiled.message_bytes
    assert compiled.signature_id(signature) == base58.encode(signature)


def test_token_transfer_checked_compilation() -> None:
    owner = bytes(range(32))
    mint = bytes([3] * 32)
    source = bytes([4] * 32)
    destination = bytes([5] * 32)
    instruction = sol_tx.token_transfer_checked(
        source_ata=source, mint=mint, destination_ata=destination,
        owner=owner, amount=250_000_000, decimals=6,
    )
    compiled = sol_tx.compile_message(
        fee_payer=owner, instructions=[instruction], recent_blockhash=bytes([1] * 32)
    )
    parsed = _parse_message(compiled.message_bytes)
    assert parsed["header"][0] == 1  # only the owner signs
    ix = parsed["instructions"][0]
    assert ix["data"][0] == 12  # TransferChecked
    assert int.from_bytes(ix["data"][1:9], "little") == 250_000_000
    assert ix["data"][9] == 6
    program_key = parsed["keys"][ix["program"]]
    assert base58.encode(program_key) == keys.TOKEN_PROGRAM
