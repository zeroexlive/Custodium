"""TON cells, builders, slices, and Bag-of-Cells (BoC).

TON's universal data structure is the **cell**: up to 1023 bits
of data plus up to 4 references to other cells. A cell's hash is
the SHA-256 of its representation bytes (descriptors ‖ data ‖
reference depths ‖ reference hashes), which is what makes cell
hashes serve as account ids and message hashes.

This module implements ordinary (non-exotic) cells only:
construction (Builder), parsing/reading (Slice), representation
hashing, and BoC serialisation/deserialisation including the
CRC32C checksum — enough to build wallet-v4 messages and to parse
provider responses. No third-party TON library is used.
"""

from __future__ import annotations

import hashlib
import struct

MAX_BITS = 1023
MAX_REFS = 4
_BOC_MAGIC = bytes.fromhex("b5ee9c72")


class CellError(ValueError):
    """Raised for malformed cells / BoC / slice reads."""


# --------------------------------------------------------------- CRC32C

def _build_crc32c_table() -> list[int]:
    poly = 0x82F63B78
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ (poly if crc & 1 else 0)
        table.append(crc)
    return table


_CRC32C_TABLE = _build_crc32c_table()


def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc = _CRC32C_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


# ----------------------------------------------------------------- Cell

class Cell:
    """An immutable ordinary cell: a bit string + ordered refs."""

    __slots__ = ("_bits", "_bit_len", "refs", "_hash", "_depth")

    def __init__(self, bits: bytes, bit_len: int, refs: tuple[Cell, ...] = ()) -> None:
        if bit_len > MAX_BITS:
            raise CellError("cell exceeds 1023 bits")
        if len(refs) > MAX_REFS:
            raise CellError("cell exceeds 4 references")
        expected = (bit_len + 7) // 8
        if len(bits) != expected:
            raise CellError("bit data length does not match bit length")
        self._bits = bits
        self._bit_len = bit_len
        self.refs = tuple(refs)
        self._hash: bytes | None = None
        self._depth: int | None = None

    @property
    def bit_len(self) -> int:
        return self._bit_len

    @property
    def bits(self) -> bytes:
        return self._bits

    def _augmented_data(self) -> bytes:
        """Data bytes with the augmentation marker bit appended
        when the bit length is not a multiple of 8."""
        if self._bit_len % 8 == 0:
            return self._bits
        data = bytearray(self._bits)
        remainder = self._bit_len % 8
        # The partial byte currently holds `remainder` top bits;
        # set the marker bit right after them.
        data[-1] |= 1 << (7 - remainder)
        # bits above the stored ones must be zero already by
        # construction; mask defensively below the marker.
        mask_below = (1 << (7 - remainder)) - 1
        data[-1] &= ~mask_below & 0xFF | (1 << (7 - remainder))
        return bytes(data)

    def _descriptors(self) -> tuple[int, int]:
        d1 = len(self.refs)  # ordinary cell, level 0, not exotic
        full_bytes, remainder = divmod(self._bit_len, 8)
        d2 = full_bytes * 2 + (1 if remainder else 0)
        return d1, d2

    @property
    def depth(self) -> int:
        if self._depth is None:
            self._depth = 0 if not self.refs else 1 + max(r.depth for r in self.refs)
        return self._depth

    def hash(self) -> bytes:
        if self._hash is None:
            d1, d2 = self._descriptors()
            repr_bytes = bytearray([d1, d2])
            repr_bytes += self._augmented_data()
            for ref in self.refs:
                repr_bytes += struct.pack(">H", ref.depth)
            for ref in self.refs:
                repr_bytes += ref.hash()
            self._hash = hashlib.sha256(bytes(repr_bytes)).digest()
        return self._hash

    def begin_parse(self) -> Slice:
        return Slice(self)

    def to_boc(self) -> bytes:
        return serialize_boc(self)

    @staticmethod
    def from_boc(data: bytes) -> Cell:
        cells = parse_boc(data)
        if len(cells) != 1:
            raise CellError(f"expected a single-root BoC, got {len(cells)} roots")
        return cells[0]

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Cell)
            and self._bits == other._bits
            and self._bit_len == other._bit_len
            and self.refs == other.refs
        )

    def __hash__(self) -> int:
        return hash((self._bits, self._bit_len, self.refs))

    def __repr__(self) -> str:  # pragma: no cover - display only
        return f"Cell(bits={self._bit_len}, refs={len(self.refs)}, hash={self.hash().hex()[:12]})"


EMPTY_CELL = Cell(b"", 0)


# -------------------------------------------------------------- Builder

class Builder:
    """Accumulates bits and refs into a cell."""

    def __init__(self) -> None:
        self._bytes = bytearray()
        self._bit_len = 0
        self._refs: list[Cell] = []

    def _push_bit(self, bit: int) -> None:
        byte_index, bit_index = divmod(self._bit_len, 8)
        if bit_index == 0:
            self._bytes.append(0)
        if bit:
            self._bytes[byte_index] |= 1 << (7 - bit_index)
        self._bit_len += 1
        if self._bit_len > MAX_BITS:
            raise CellError("cell exceeds 1023 bits")

    def store_bit(self, bit: int | bool) -> Builder:
        self._push_bit(1 if bit else 0)
        return self

    def store_uint(self, value: int, bits: int) -> Builder:
        if value < 0 or value >= (1 << bits):
            raise CellError(f"value {value} does not fit in {bits} bits")
        for i in range(bits - 1, -1, -1):
            self._push_bit((value >> i) & 1)
        return self

    def store_int(self, value: int, bits: int) -> Builder:
        if value < -(1 << (bits - 1)) or value >= (1 << (bits - 1)):
            raise CellError(f"value {value} does not fit in {bits} signed bits")
        return self.store_uint(value & ((1 << bits) - 1), bits)

    def store_bytes(self, data: bytes) -> Builder:
        """Store raw bytes at the current bit position (TON
        builders are bit-oriented; alignment is not required)."""
        for byte in data:
            self.store_uint(byte, 8)
        return self

    def store_coins(self, value: int) -> Builder:
        """VarUInteger 16: a 4-bit byte length, then the value."""
        if value < 0:
            raise CellError("coins cannot be negative")
        if value == 0:
            return self.store_uint(0, 4)
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        if len(raw) > 15:
            raise CellError("coins value too large")
        self.store_uint(len(raw), 4)
        return self.store_bytes(raw)

    def store_address(self, raw: str | None) -> Builder:
        """MsgAddress: addr_none (00) or addr_std (10, no anycast,
        int8 workchain, 256-bit account id)."""
        if raw is None:
            return self.store_uint(0, 2)
        workchain_text, _, hex_id = raw.partition(":")
        account_id = bytes.fromhex(hex_id)
        if len(account_id) != 32:
            raise CellError("account id must be 32 bytes")
        self.store_uint(0b10, 2)
        self.store_bit(0)  # no anycast
        self.store_int(int(workchain_text), 8)
        return self.store_bytes(account_id)

    def store_ref(self, cell: Cell) -> Builder:
        if len(self._refs) >= MAX_REFS:
            raise CellError("cell exceeds 4 references")
        self._refs.append(cell)
        return self

    def store_builder(self, other: Builder) -> Builder:
        """Inline another builder's bits and refs."""
        for i in range(other._bit_len):
            byte = other._bytes[i // 8]
            self._push_bit((byte >> (7 - (i % 8))) & 1)
        for ref in other._refs:
            self.store_ref(ref)
        return self

    def end_cell(self) -> Cell:
        return Cell(bytes(self._bytes), self._bit_len, tuple(self._refs))


def begin_cell() -> Builder:
    return Builder()


# ---------------------------------------------------------------- Slice

class Slice:
    """A forward-only reader over a cell's bits and refs."""

    def __init__(self, cell: Cell) -> None:
        self._cell = cell
        self._pos = 0
        self._ref_pos = 0

    @property
    def remaining_bits(self) -> int:
        return self._cell.bit_len - self._pos

    def _read_bit(self) -> int:
        if self._pos >= self._cell.bit_len:
            raise CellError("slice exhausted")
        byte = self._cell.bits[self._pos // 8]
        bit = (byte >> (7 - (self._pos % 8))) & 1
        self._pos += 1
        return bit

    def read_bit(self) -> bool:
        return bool(self._read_bit())

    def read_uint(self, bits: int) -> int:
        value = 0
        for _ in range(bits):
            value = (value << 1) | self._read_bit()
        return value

    def read_int(self, bits: int) -> int:
        value = self.read_uint(bits)
        if value >= (1 << (bits - 1)):
            value -= 1 << bits
        return value

    def read_bytes(self, count: int) -> bytes:
        out = bytearray()
        for _ in range(count):
            out.append(self.read_uint(8))
        return bytes(out)

    def read_coins(self) -> int:
        length = self.read_uint(4)
        if length == 0:
            return 0
        return int.from_bytes(self.read_bytes(length), "big")

    def read_address(self) -> str | None:
        """Returns the raw `workchain:hex` form, or None for addr_none."""
        tag = self.read_uint(2)
        if tag == 0:
            return None
        if tag != 0b10:
            raise CellError(f"unsupported MsgAddress tag: {tag}")
        if self.read_bit():
            raise CellError("anycast addresses are not supported")
        workchain = self.read_int(8)
        account_id = self.read_bytes(32)
        return f"{workchain}:{account_id.hex()}"

    def read_ref(self) -> Cell:
        if self._ref_pos >= len(self._cell.refs):
            raise CellError("no more references")
        ref = self._cell.refs[self._ref_pos]
        self._ref_pos += 1
        return ref


# ------------------------------------------------------------------- BoC

def _collect_cells(root: Cell) -> list[Cell]:
    """Root-first topological order (pre-order DFS, deduplicated
    by identity — shared subcells are serialised once)."""
    ordered: list[Cell] = []
    seen: set[int] = set()

    def visit(cell: Cell) -> None:
        if id(cell) in seen:
            return
        seen.add(id(cell))
        ordered.append(cell)
        for ref in cell.refs:
            visit(ref)

    visit(root)
    return ordered


def serialize_boc(root: Cell, *, with_crc: bool = True) -> bytes:
    cells = _collect_cells(root)
    index = {id(cell): i for i, cell in enumerate(cells)}
    size_bytes = max(1, (len(cells).bit_length() + 7) // 8)
    cell_data = bytearray()
    for cell in cells:
        d1, d2 = cell._descriptors()
        cell_data.append(d1)
        cell_data.append(d2)
        cell_data += cell._augmented_data()
        for ref in cell.refs:
            cell_data += index[id(ref)].to_bytes(size_bytes, "big")
    off_bytes = max(1, (len(cell_data).bit_length() + 7) // 8)

    header = bytearray(_BOC_MAGIC)
    # Flags byte: has_idx(1) = 0, hash_crc32(1), flags(2) = 0,
    # size_bytes(3).
    flags_byte = (0b0100_0000 if with_crc else 0) | (size_bytes & 0x07)
    header.append(flags_byte)
    header.append(off_bytes)
    header += len(cells).to_bytes(size_bytes, "big")
    header += (1).to_bytes(size_bytes, "big")  # one root
    header += (0).to_bytes(size_bytes, "big")  # no absent cells
    header += len(cell_data).to_bytes(off_bytes, "big")
    header += (0).to_bytes(size_bytes, "big")  # root index 0
    payload = bytes(header) + bytes(cell_data)
    if with_crc:
        payload += struct.pack("<I", crc32c(payload))
    return payload


def parse_boc(data: bytes) -> list[Cell]:
    """Parse a BoC, returning its root cells."""
    if len(data) < 6 or data[:4] != _BOC_MAGIC:
        raise CellError("not a BoC (bad magic)")
    flags = data[4]
    # Flags byte layout: has_idx(1) hash_crc32(1) flags(2)
    # size_bytes(3).
    has_idx = bool(flags & 0b1000_0000)
    with_crc = bool(flags & 0b0100_0000)
    size_bytes = flags & 0b0000_0111
    off_bytes = data[5]
    pos = 6

    def read_int(nbytes: int) -> int:
        nonlocal pos
        value = int.from_bytes(data[pos : pos + nbytes], "big")
        pos += nbytes
        return value

    cells_num = read_int(size_bytes)
    roots_num = read_int(size_bytes)
    read_int(size_bytes)  # absent count
    total_size = read_int(off_bytes)
    root_indices = [read_int(size_bytes) for _ in range(roots_num)]
    if has_idx:
        pos += cells_num * off_bytes
    cells_region = data[pos : pos + total_size]
    if with_crc:
        expected = struct.unpack("<I", data[pos + total_size : pos + total_size + 4])[0]
        if crc32c(data[: pos + total_size]) != expected:
            raise CellError("BoC CRC32C mismatch")

    raw_cells: list[tuple[bytes, int, list[int]]] = []
    cpos = 0
    for _ in range(cells_num):
        if cpos + 2 > len(cells_region):
            raise CellError("truncated BoC cell data")
        d1, d2 = cells_region[cpos], cells_region[cpos + 1]
        cpos += 2
        ref_count = d1 & 0x07
        if d1 & 0x08:
            raise CellError("exotic cells are not supported")
        byte_len = (d2 + 1) // 2
        payload = cells_region[cpos : cpos + byte_len]
        cpos += byte_len
        if d2 % 2 == 0:
            bit_len = (d2 // 2) * 8
            bits = payload
        else:
            # Find the augmentation marker in the final byte.
            last = payload[-1]
            marker = 0
            for i in range(8):
                if (last >> i) & 1:
                    marker = i
                    break
            bits_in_last = 7 - marker
            bit_len = (byte_len - 1) * 8 + bits_in_last
            if bits_in_last == 0:
                bits = bytes(payload[:-1])
            else:
                keep_mask = (0xFF << (8 - bits_in_last)) & 0xFF
                bits = bytes(payload[:-1]) + bytes([last & keep_mask])
        refs = []
        for _ in range(ref_count):
            refs.append(int.from_bytes(cells_region[cpos : cpos + size_bytes], "big"))
            cpos += size_bytes
        raw_cells.append((bits, bit_len, refs))

    built: list[Cell | None] = [None] * cells_num

    def build(i: int) -> Cell:
        if built[i] is not None:
            return built[i]  # type: ignore[return-value]
        bits, bit_len, refs = raw_cells[i]
        cell = Cell(bits, bit_len, tuple(build(r) for r in refs))
        built[i] = cell
        return cell

    return [build(i) for i in root_indices]
