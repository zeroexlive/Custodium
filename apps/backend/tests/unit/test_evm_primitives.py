"""EVM primitives against published vectors (Phase 4).

The strongest checks here are external: the EIP-155 worked example
(sighash + signed transaction bytes must match the EIP exactly) and
the well-known generator-point address. The type-2 round-trip uses
the `cryptography` package as an independent ECDSA implementation
with a published test key — test-only code; production signing is
MPC-only and lives behind the signer port.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from waas.modules.evm import keys, rlp, transactions

# The EIP-155 example private key (published in the EIP itself).
EIP155_KEY = bytes.fromhex(
    "4646464646464646464646464646464646464646464646464646464646464646"
)


def _test_signer():
    return ec.derive_private_key(int.from_bytes(EIP155_KEY, "big"), ec.SECP256K1())


def _pubkey_bytes(priv) -> bytes:
    numbers = priv.public_key().public_numbers()
    return numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")


def _sign_digest(priv, digest: bytes) -> tuple[int, int]:
    der = priv.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    r, s = utils.decode_dss_signature(der)
    return r, s


# ---------------------------------------------------------------- RLP


@pytest.mark.parametrize(
    ("item", "expected_hex"),
    [
        (b"", "80"),
        (b"dog", "83646f67"),
        (1024, "820400"),
        (0, "80"),
        ([], "c0"),
        ([[], [[]], [[], [[]]]], "c7c0c1c0c3c0c1c0"),
        (
            b"Lorem ipsum dolor sit amet, consectetur adipisicing elit",
            "b8384c6f72656d20697073756d20646f6c6f722073697420616d65742c20636f6e"
            "7365637465747572206164697069736963696e6720656c6974",
        ),
    ],
)
def test_rlp_vectors(item, expected_hex) -> None:
    assert rlp.encode(item).hex() == expected_hex


def test_rlp_roundtrip() -> None:
    item = [b"cat", 42, [b"dog", 0], b"x" * 100]
    decoded = rlp.decode(rlp.encode(item))
    assert decoded == [b"cat", b"\x2a", [b"dog", b""], b"x" * 100]


def test_rlp_rejects_trailing_bytes() -> None:
    with pytest.raises(rlp.RlpError):
        rlp.decode(b"\x83dog\x00")


# ---------------------------------------------------------------- keys


def test_keccak_vectors() -> None:
    assert keys.keccak256(b"").hex() == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    assert keys.keccak256(b"transfer(address,uint256)")[:4].hex() == "a9059cbb"


def test_address_from_generator_point() -> None:
    # Private key 1 -> the generator point -> this famous address.
    g = keys.GX.to_bytes(32, "big") + keys.GY.to_bytes(32, "big")
    assert keys.address_from_public_key(g) == "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"
    assert keys.address_from_public_key(b"\x04" + g) == (
        "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"
    )


def test_address_from_eip155_key() -> None:
    pub = _pubkey_bytes(_test_signer())
    assert keys.address_from_public_key(pub) == "0x9d8A62f656a8d1615C1294fd71e9CFb3E4855A4F"


def test_recovery_roundtrip() -> None:
    priv = _test_signer()
    pub = _pubkey_bytes(priv)
    digest = keys.keccak256(b"custodium recovery test")
    r, s = _sign_digest(priv, digest)
    recid = keys.find_recovery_id(digest, r, s, pub)
    assert keys.recover_address(digest, r, s, recid) == keys.address_from_public_key(pub)
    with pytest.raises(ValueError):
        keys.find_recovery_id(digest, r, s, b"\x11" * 64)


# --------------------------------------------------------- transactions


def test_eip155_canonical_vector() -> None:
    """The worked example from EIP-155 itself, byte for byte."""
    tx = transactions.build_native_transfer(
        chain_id=1,
        nonce=9,
        to="0x3535353535353535353535353535353535353535",
        amount_wei=10**18,
        gas_price=20_000_000_000,
    )
    assert tx.sighash().hex() == (
        "daf5a779ae972f972197303d7b574746c7ef83eadac0f2791ad23db92e4c8e53"
    )
    r = 0x28EF61340BD939BC2195FE537567866003E1A15D3C71FF63E1590620AA636276
    s = 0x67CBE9D8997F761AECB703304B3800CCF555C9F3DC64214B297FB1966A3B6D83
    raw = tx.assemble_signed(r, s, 0)
    assert raw.hex() == (
        "f86c098504a817c800825208943535353535353535353535353535353535353535880"
        "de0b6b3a76400008025a028ef61340bd939bc2195fe537567866003e1a15d3c71ff63e"
        "1590620aa636276a067cbe9d8997f761aecb703304b3800ccf555c9f3dc64214b297f"
        "b1966a3b6d83"
    )
    # And the sender of that signed transaction is the EIP-155 key's address.
    assert keys.recover_address(tx.sighash(), r, s, 0) == (
        "0x9d8A62f656a8d1615C1294fd71e9CFb3E4855A4F"
    )


def test_type2_roundtrip_with_independent_signer() -> None:
    priv = _test_signer()
    pub = _pubkey_bytes(priv)
    tx = transactions.build_native_transfer(
        chain_id=11155111,
        nonce=3,
        to="0x2222222222222222222222222222222222222222",
        amount_wei=12345,
        max_fee_per_gas=30_000_000_000,
        max_priority_fee_per_gas=1_500_000_000,
    )
    assert tx.signing_payload()[0] == 0x02
    r, s = _sign_digest(priv, tx.sighash())
    recid = keys.find_recovery_id(tx.sighash(), r, s, pub)
    raw = tx.assemble_signed(r, s, recid)
    assert raw[0] == 0x02
    decoded = rlp.decode(raw[1:])
    assert int.from_bytes(decoded[0], "big") == 11155111
    assert keys.recover_address(tx.sighash(), r, s, recid) == keys.address_from_public_key(pub)


def test_erc20_transfer_encoding() -> None:
    data = transactions.erc20_transfer_data(
        "0x1111111111111111111111111111111111111111", 1_000_000
    )
    assert data[:4].hex() == "a9059cbb"
    assert data[4:36] == bytes(12) + bytes.fromhex("11" * 20)
    assert int.from_bytes(data[36:], "big") == 1_000_000
    tx = transactions.build_token_transfer(
        chain_id=56,
        nonce=0,
        token_contract="0x55d398326f99059fF775485246999027B3197955",
        to="0x1111111111111111111111111111111111111111",
        amount=5,
        gas_price=5_000_000_000,
    )
    assert tx.value == 0  # token transfers carry no native value
    assert tx.to == "0x55d398326f99059ff775485246999027b3197955"


def test_cross_language_sighash_fixtures() -> None:
    """These two sighashes are ALSO hardcoded in the Rust evaluation
    harness (Phase 4 cross-proof), where a threshold group signs
    them and ecrecover is checked. If a builder change moves either
    hash, both suites must be updated together — that is the point
    of pinning them here."""
    native = transactions.build_native_transfer(
        chain_id=11155111, nonce=0,
        to="0x2222222222222222222222222222222222222222",
        amount_wei=100_000_000_000_000_000,
        max_fee_per_gas=30_000_000_000, max_priority_fee_per_gas=1_000_000_000,
    )
    assert native.sighash().hex() == (
        "f591bd8f35eeaca177bf3828c72790ab670b38813856fd20f4bc97626f3b8f5d"
    )
    token = transactions.build_token_transfer(
        chain_id=11155111, nonce=1,
        token_contract="0x5555555555555555555555555555555555555555",
        to="0x2222222222222222222222222222222222222222",
        amount=25_000_000, gas_limit=50_000,
        max_fee_per_gas=30_000_000_000, max_priority_fee_per_gas=1_000_000_000,
    )
    assert token.sighash().hex() == (
        "4a006560d91b8351fc6b99d64313b51ee7fef28df7fcb86161717658d32ed881"
    )


def test_fee_field_validation() -> None:
    with pytest.raises(ValueError):
        transactions.build_native_transfer(
            chain_id=1, nonce=0, to="0x" + "11" * 20, amount_wei=1,
        )
    with pytest.raises(ValueError):
        transactions.build_native_transfer(
            chain_id=1, nonce=0, to="0x" + "11" * 20, amount_wei=1,
            max_fee_per_gas=10, max_priority_fee_per_gas=11,
        )
