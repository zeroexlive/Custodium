"""Wallet V4R2 contracts: address derivation and transfer building.

The V4R2 code cell below is taken **verbatim** from the official
`@ton/ton` SDK (`src/wallets/v4/WalletContractV4.ts`, fetched
2026-11-12 from the ton-org/ton repository) — wallet code is a
consensus artifact and must never be hand-edited. The unit tests
pin our derivation against the SDK's own spec vector
(`randomTestKey("v4-treasure")` →
`EQDnBF4JTFKHTYjulEJyNd4dstLGH1m51UrLdu01_tw4z2Au`), which
exercises the whole cells/BoC/hash/address pipeline.

Signing layout (createWalletTransferV4): the signable cell is
`wallet_id(32) ‖ valid_until(32) ‖ seqno(32) ‖ op=0(8) ‖
send_mode(8) ‖ ^internal_message`; the Ed25519 signature over its
hash is packed in front of the body cell. Signing goes through
the shared Ed25519 signer port (FROST side, review-gated) — the
port signs the 32-byte cell hash, matching TON's convention of
signing hashes rather than whole cells.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

from . import addresses
from .cells import Cell, begin_cell

WALLET_V4_CODE_BOC = (
    "te6ccgECFAEAAtQAART/APSkE/S88sgLAQIBIAIDAgFIBAUE+PKDCNcYINMf0x/THwL4I7vyZO1E0NMf0x/T//QE0VFD"
    "uvKhUVG68qIF+QFUEGT5EPKj+AAkpMjLH1JAyx9SMMv/UhD0AMntVPgPAdMHIcAAn2xRkyDXSpbTB9QC+wDoMOAhwAHj"
    "ACHAAuMAAcADkTDjDQOkyMsfEssfy/8QERITAubQAdDTAyFxsJJfBOAi10nBIJJfBOAC0x8hghBwbHVnvSKCEGRzdHK9"
    "sJJfBeAD+kAwIPpEAcjKB8v/ydDtRNCBAUDXIfQEMFyBAQj0Cm+hMbOSXwfgBdM/yCWCEHBsdWe6kjgw4w0DghBkc3Ry"
    "upJfBuMNBgcCASAICQB4AfoA9AQw+CdvIjBQCqEhvvLgUIIQcGx1Z4MesXCAGFAEywUmzxZY+gIZ9ADLaRfLH1Jgyz8g"
    "yYBA+wAGAIpQBIEBCPRZMO1E0IEBQNcgyAHPFvQAye1UAXKwjiOCEGRzdHKDHrFwgBhQBcsFUAPPFiP6AhPLassfyz/J"
    "gED7AJJfA+ICASAKCwBZvSQrb2omhAgKBrkPoCGEcNQICEekk30pkQzmkD6f+YN4EoAbeBAUiYcVnzGEAgFYDA0AEbjJ"
    "ftRNDXCx+AA9sp37UTQgQFA1yH0BDACyMoHy//J0AGBAQj0Cm+hMYAIBIA4PABmtznaiaEAga5Drhf/AABmvHfaiaEAQ"
    "a5DrhY/AAG7SB/oA1NQi+QAFyMoHFcv/ydB3dIAYyMsFywIizxZQBfoCFMtrEszMyXP7AMhAFIEBCPRR8qcCAHCBAQjX"
    "GPoA0z/IVCBHgQEI9FHyp4IQbm90ZXB0gBjIywXLAlAGzxZQBPoCFMtqEssfyz/Jc/sAAgBsgQEI1xj6ANM/MFIkgQE"
    "I9Fnyp4IQZHN0cnB0gBjIywXLAlAFzxZQA/oCE8tqyx8Syz/Jc/sAAAr0AMntVA=="
)

DEFAULT_WALLET_ID_BASE = 698983191  # @ton/ton: 698983191 + workchain
SEND_MODE_PAY_FEES_SEPARATELY = 1
SEND_MODE_IGNORE_ERRORS = 2

JETTON_TRANSFER_OP = 0xF8A7EA5
JETTON_INTERNAL_TRANSFER_OP = 0x178D4519
JETTON_NOTIFICATION_OP = 0x7362D09C
EXCESSES_OP = 0xD53276DB


def wallet_code_cell() -> Cell:
    return Cell.from_boc(base64.b64decode(WALLET_V4_CODE_BOC))


def wallet_data_cell(*, public_key: bytes, wallet_id: int) -> Cell:
    if len(public_key) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes")
    return (
        begin_cell()
        .store_uint(0, 32)  # seqno
        .store_uint(wallet_id, 32)
        .store_bytes(public_key)
        .store_bit(0)  # empty plugins dict
        .end_cell()
    )


def state_init_cell(*, code: Cell, data: Cell) -> Cell:
    return (
        begin_cell()
        .store_bit(0)  # no split_depth
        .store_bit(0)  # no special
        .store_bit(1)  # code present
        .store_ref(code)
        .store_bit(1)  # data present
        .store_ref(data)
        .store_bit(0)  # no library
        .end_cell()
    )


def wallet_id_for(workchain: int) -> int:
    return DEFAULT_WALLET_ID_BASE + workchain


def wallet_address_raw(*, public_key: bytes, workchain: int = 0) -> str:
    """The raw address of the v4r2 wallet for an Ed25519 key."""
    init = state_init_cell(
        code=wallet_code_cell(),
        data=wallet_data_cell(public_key=public_key, wallet_id=wallet_id_for(workchain)),
    )
    return addresses.to_raw(workchain, init.hash())


def internal_message(
    *,
    destination_raw: str,
    value_nano: int,
    bounce: bool = True,
    body: Cell | None = None,
    init: Cell | None = None,
) -> Cell:
    """A relaxed internal message (the wallet contract fills the
    source). Fees are zeroed in the relaxed form, per @ton/core."""
    builder = (
        begin_cell()
        .store_bit(0)  # int_msg_info
        .store_bit(1)  # ihr_disabled
        .store_bit(bounce)
        .store_bit(0)  # bounced
        .store_address(None)  # src: filled by the wallet contract
        .store_address(destination_raw)
        .store_coins(value_nano)
        .store_bit(0)  # no extra currencies
        .store_coins(0)  # ihr_fee
        .store_coins(0)  # fwd_fee
        .store_uint(0, 64)  # created_lt
        .store_uint(0, 32)  # created_at
    )
    if init is None:
        builder.store_bit(0)
    else:
        builder.store_bit(1).store_bit(0).store_builder(_builder_of(init))
    if body is None:
        builder.store_bit(0)
    else:
        builder.store_bit(1).store_ref(body)
    return builder.end_cell()


def _builder_of(cell: Cell):
    """Rebuild a Builder holding an existing cell's bits+refs
    (used for inline StateInit embedding)."""
    from .cells import Builder, Slice

    builder = Builder()
    slice_ = Slice(cell)
    for _ in range(cell.bit_len):
        builder.store_bit(1 if slice_.read_bit() else 0)
    for ref in cell.refs:
        builder.store_ref(ref)
    return builder


@dataclass(frozen=True)
class PreparedTransfer:
    signing_hash: bytes  # what the Ed25519 port must sign
    signing_cell: Cell

    def complete(self, signature: bytes, *, wallet_raw: str, init: Cell | None) -> Cell:
        """Assemble the external message cell ready for broadcast."""
        if len(signature) != 64:
            raise ValueError("Ed25519 signature must be 64 bytes")
        body_builder = begin_cell().store_bytes(signature)
        body_builder.store_builder(_builder_of(self.signing_cell))
        body = body_builder.end_cell()
        builder = (
            begin_cell()
            .store_uint(0b10, 2)  # ext_in_msg_info
            .store_address(None)  # external source
            .store_address(wallet_raw)
            .store_coins(0)  # import_fee
        )
        if init is None:
            builder.store_bit(0)
        else:
            builder.store_bit(1).store_bit(0).store_builder(_builder_of(init))
        builder.store_bit(1).store_ref(body)
        return builder.end_cell()


def prepare_transfer(
    *,
    public_key: bytes,
    seqno: int,
    internal: Cell,
    send_mode: int = SEND_MODE_PAY_FEES_SEPARATELY | SEND_MODE_IGNORE_ERRORS,
    valid_until: int | None = None,
    workchain: int = 0,
) -> PreparedTransfer:
    if valid_until is None:
        valid_until = int(time.time()) + 3600  # MPC ceremony budget
    signing_cell = (
        begin_cell()
        .store_uint(wallet_id_for(workchain), 32)
        .store_uint(valid_until, 32)
        .store_uint(seqno, 32)
        .store_uint(0, 8)  # op: simple send
        .store_uint(send_mode, 8)
        .store_ref(internal)
        .end_cell()
    )
    return PreparedTransfer(signing_hash=signing_cell.hash(), signing_cell=signing_cell)


def jetton_transfer_body(
    *,
    amount: int,
    destination_raw: str,
    response_raw: str,
    query_id: int = 0,
    forward_ton_nano: int = 1,
) -> Cell:
    """The Jetton `transfer` payload sent to OUR jetton wallet."""
    return (
        begin_cell()
        .store_uint(JETTON_TRANSFER_OP, 32)
        .store_uint(query_id, 64)
        .store_coins(amount)
        .store_address(destination_raw)
        .store_address(response_raw)
        .store_bit(0)  # no custom payload
        .store_coins(forward_ton_nano)
        .store_bit(0)  # empty forward payload (inline)
        .end_cell()
    )
