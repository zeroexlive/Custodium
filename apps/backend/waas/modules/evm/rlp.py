"""RLP (Recursive Length Prefix) encoding/decoding — Ethereum's
canonical serialisation. Pure implementation, no dependencies,
covering exactly the types transaction code needs: bytes, integers
(encoded as minimal big-endian byte strings; zero is the empty
string), and nested lists.

Reference: Ethereum Yellow Paper, Appendix B.
"""

from __future__ import annotations


class RlpError(ValueError):
    """Malformed RLP input."""


def _length_prefix(length: int, offset: int) -> bytes:
    if length < 56:
        return bytes([offset + length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([offset + 55 + len(raw)]) + raw


def encode(item: bytes | int | list) -> bytes:
    """Encode a bytes/int/list structure to RLP bytes."""
    if isinstance(item, int):
        if item < 0:
            raise RlpError("RLP cannot encode negative integers")
        if item == 0:
            return encode(b"")
        return encode(item.to_bytes((item.bit_length() + 7) // 8, "big"))
    if isinstance(item, (bytes, bytearray)):
        data = bytes(item)
        if len(data) == 1 and data[0] < 0x80:
            return data
        return _length_prefix(len(data), 0x80) + data
    if isinstance(item, (list, tuple)):
        payload = b"".join(encode(child) for child in item)
        return _length_prefix(len(payload), 0xC0) + payload
    raise RlpError(f"unsupported RLP type: {type(item)!r}")


def _read_length(data: bytes, pos: int, len_of_len: int) -> tuple[int, int]:
    if len_of_len == 0 or pos + len_of_len > len(data):
        raise RlpError("truncated length-of-length")
    raw = data[pos : pos + len_of_len]
    if raw[0] == 0:
        raise RlpError("non-canonical RLP: leading zero in length")
    return int.from_bytes(raw, "big"), pos + len_of_len


def _decode_at(data: bytes, pos: int) -> tuple[bytes | list, int]:
    if pos >= len(data):
        raise RlpError("unexpected end of input")
    b0 = data[pos]
    if b0 < 0x80:
        return bytes([b0]), pos + 1
    if b0 < 0xB8:  # short string
        length = b0 - 0x80
        start, end = pos + 1, pos + 1 + length
        if end > len(data):
            raise RlpError("truncated string")
        if length == 1 and data[start] < 0x80:
            raise RlpError("non-canonical RLP: single byte below 0x80 must encode itself")
        return data[start:end], end
    if b0 < 0xC0:  # long string
        length, start = _read_length(data, pos + 1, b0 - 0xB7)
        end = start + length
        if end > len(data):
            raise RlpError("truncated long string")
        return data[start:end], end
    if b0 < 0xF8:  # short list
        length = b0 - 0xC0
        start, end = pos + 1, pos + 1 + length
        if end > len(data):
            raise RlpError("truncated list")
        return _decode_list_payload(data, start, end), end
    # long list
    length, start = _read_length(data, pos + 1, b0 - 0xF7)
    end = start + length
    if end > len(data):
        raise RlpError("truncated long list")
    return _decode_list_payload(data, start, end), end


def _decode_list_payload(data: bytes, start: int, end: int) -> list:
    items: list = []
    pos = start
    while pos < end:
        item, pos = _decode_at(data, pos)
        items.append(item)
    if pos != end:
        raise RlpError("list payload length mismatch")
    return items


def decode(data: bytes) -> bytes | list:
    """Decode exactly one RLP item; trailing bytes are an error.
    Strings decode to bytes (integers come back as their byte form —
    use int.from_bytes where an integer is expected)."""
    item, pos = _decode_at(data, 0)
    if pos != len(data):
        raise RlpError("trailing bytes after RLP item")
    return item
