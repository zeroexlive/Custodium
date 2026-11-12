"""secp256k1 public-key mathematics for EVM chains: address
derivation and sender recovery (ecrecover). No private-key material
of any kind lives in this module — it works with public keys,
digests, and signatures only.

Address rule (Ethereum/Yellow Paper): address = last 20 bytes of
Keccak-256 of the 64-byte uncompressed public key (x || y, without
the 0x04 prefix), displayed with the EIP-55 checksum.
"""

from __future__ import annotations

from Crypto.Hash import keccak

# secp256k1 domain parameters.
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def keccak256(data: bytes) -> bytes:
    return keccak.new(data=data, digest_bits=256).digest()


def _checksum_address(address_bytes: bytes) -> str:
    """EIP-55 checksummed hex encoding of a 20-byte address."""
    hex_lower = address_bytes.hex()
    digest = keccak256(hex_lower.encode("ascii")).hex()
    out = []
    for char, nibble in zip(hex_lower, digest[:40], strict=True):
        out.append(char.upper() if int(nibble, 16) >= 8 else char)
    return "0x" + "".join(out)


def normalize_address(address: str) -> str:
    """Validate an EVM address and return its lowercase 0x form."""
    if not isinstance(address, str) or not address.startswith("0x") or len(address) != 42:
        raise ValueError(f"invalid EVM address: {address!r}")
    try:
        bytes.fromhex(address[2:])
    except ValueError as exc:
        raise ValueError(f"invalid EVM address: {address!r}") from exc
    return address.lower()


def address_from_public_key(public_key: bytes) -> str:
    """Derive the EIP-55 address from a public key.

    Accepts the 65-byte uncompressed form (0x04 || x || y) or the
    bare 64-byte x || y form — e.g. a threshold group's shared
    public key as produced by the MPC key-generation ceremony.
    """
    if len(public_key) == 65 and public_key[0] == 0x04:
        public_key = public_key[1:]
    if len(public_key) != 64:
        raise ValueError("expected a 64-byte (or 65-byte uncompressed) public key")
    return _checksum_address(keccak256(public_key)[-20:])


def _point_add(p1: tuple[int, int] | None, p2: tuple[int, int] | None) -> tuple[int, int] | None:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        slope = (3 * x1 * x1) * pow(2 * y1, -1, P) % P
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (slope * slope - x1 - x2) % P
    y3 = (slope * (x1 - x3) - y1) % P
    return x3, y3


def _point_mul(k: int, point: tuple[int, int]) -> tuple[int, int] | None:
    result: tuple[int, int] | None = None
    addend: tuple[int, int] | None = point
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def recover_public_key(digest: bytes, r: int, s: int, recovery_id: int) -> bytes:
    """ECDSA public-key recovery over secp256k1 (the ecrecover math).

    Returns the 64-byte x || y public key for the given recovery id
    (0 or 1, the y-parity of the ephemeral point). Raises ValueError
    for out-of-range signature values or an unrecoverable point.
    """
    if len(digest) != 32:
        raise ValueError("digest must be 32 bytes")
    if not (1 <= r < N and 1 <= s < N):
        raise ValueError("signature values out of range")
    if recovery_id not in (0, 1):
        raise ValueError("recovery_id must be 0 or 1")
    x = r  # recovery ids 0/1 assume x = r (x = r + n is cryptographically negligible)
    # Solve y^2 = x^3 + 7 (mod p); p % 4 == 3 so sqrt is a^( (p+1)/4 ).
    alpha = (pow(x, 3, P) + 7) % P
    beta = pow(alpha, (P + 1) // 4, P)
    if (beta * beta) % P != alpha:
        raise ValueError("no curve point for this r")
    y = beta if (beta & 1) == recovery_id else P - beta
    point_r = (x, y)
    z = int.from_bytes(digest, "big")
    r_inv = pow(r, -1, N)
    # Q = r^-1 (s*R - z*G)
    s_r = _point_mul(s, point_r)
    z_g = _point_mul(z % N, (GX, GY))
    neg_z_g = (z_g[0], (-z_g[1]) % P) if z_g else None
    q = _point_mul(r_inv, _point_add(s_r, neg_z_g))
    if q is None:
        raise ValueError("recovered point at infinity")
    return q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big")


def recover_address(digest: bytes, r: int, s: int, recovery_id: int) -> str:
    """The EIP-55 sender address for a signature over a digest."""
    return address_from_public_key(recover_public_key(digest, r, s, recovery_id))


def find_recovery_id(digest: bytes, r: int, s: int, expected_public_key: bytes) -> int:
    """Determine whether recovery id 0 or 1 reproduces the expected
    public key — used to compute `v` for a threshold signature, whose
    signers cannot report a recovery id."""
    expected = expected_public_key[-64:]
    for candidate in (0, 1):
        try:
            if recover_public_key(digest, r, s, candidate) == expected:
                return candidate
        except ValueError:
            continue
    raise ValueError("signature does not correspond to the expected public key")
