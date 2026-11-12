"""Base58 encoding (Bitcoin alphabet) — Solana's address/signature
text form. Case-sensitive and NOT checksummed: a corrupted string
decodes to different bytes, so consumers must validate lengths."""

from __future__ import annotations

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {c: i for i, c in enumerate(_ALPHABET)}


class Base58Error(ValueError):
    """Raised on invalid base58 input."""


def encode(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    chars = []
    while number > 0:
        number, rem = divmod(number, 58)
        chars.append(_ALPHABET[rem])
    for b in data:
        if b == 0:
            chars.append("1")
        else:
            break
    return "".join(reversed(chars))


def decode(text: str) -> bytes:
    number = 0
    for char in text:
        if char not in _INDEX:
            raise Base58Error(f"invalid base58 character: {char!r}")
        number = number * 58 + _INDEX[char]
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading = len(text) - len(text.lstrip("1"))
    return b"\x00" * leading + body
