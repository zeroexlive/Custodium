"""Solana legacy transaction compilation.

Implements the legacy message format (header, account keys,
blockhash, compiled instructions) and the three instructions the
platform needs: SystemProgram transfer, SPL Token
TransferChecked, and Associated Token Account creation
(idempotent). Versioned (v0 / address-lookup-table) transactions
are deliberately NOT used: legacy messages are sufficient for
custody transfers and have the widest tooling support.

Compilation follows Solana's account-key rules: the fee payer is
always key 0 (signer, writable); remaining keys are deduplicated
(signer/writable flags OR-merged) and ordered signers-first,
writable-before-readonly within each class, which determines the
header counts.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import base58, keys


def shortvec(value: int) -> bytes:
    """Solana's compact-u16 length encoding."""
    if value < 0:
        raise ValueError("shortvec cannot encode negatives")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


@dataclass(frozen=True)
class AccountMeta:
    pubkey: bytes
    is_signer: bool
    is_writable: bool


@dataclass(frozen=True)
class Instruction:
    program_id: bytes
    accounts: tuple[AccountMeta, ...]
    data: bytes


@dataclass
class CompiledMessage:
    message_bytes: bytes
    account_keys: list[bytes]
    signer_keys: list[bytes] = field(default_factory=list)

    def signature_id(self, signature: bytes) -> str:
        """The transaction id: base58 of the fee payer's signature."""
        return base58.encode(signature)


def compile_message(
    *, fee_payer: bytes, instructions: list[Instruction], recent_blockhash: bytes
) -> CompiledMessage:
    if len(recent_blockhash) != 32:
        raise ValueError("recent blockhash must be 32 bytes")
    metas: dict[bytes, AccountMeta] = {}

    def add(pubkey: bytes, is_signer: bool, is_writable: bool) -> None:
        existing = metas.get(pubkey)
        if existing is None:
            metas[pubkey] = AccountMeta(pubkey, is_signer, is_writable)
        else:
            metas[pubkey] = AccountMeta(
                pubkey,
                existing.is_signer or is_signer,
                existing.is_writable or is_writable,
            )

    add(fee_payer, True, True)
    for instruction in instructions:
        add(instruction.program_id, False, False)
        for meta in instruction.accounts:
            add(meta.pubkey, meta.is_signer, meta.is_writable)

    def sort_key(item: tuple[bytes, AccountMeta]) -> tuple[int, int]:
        _pubkey, meta = item
        return (0 if meta.is_signer else 1, 0 if meta.is_writable else 1)

    others = sorted(
        ((k, v) for k, v in metas.items() if k != fee_payer), key=sort_key
    )
    ordered = [metas[fee_payer], *[meta for _k, meta in others]]
    account_keys = [meta.pubkey for meta in ordered]

    num_signers = sum(1 for m in ordered if m.is_signer)
    readonly_signed = sum(1 for m in ordered if m.is_signer and not m.is_writable)
    readonly_unsigned = sum(1 for m in ordered if not m.is_signer and not m.is_writable)
    header = bytes([num_signers, readonly_signed, readonly_unsigned])

    index = {key: i for i, key in enumerate(account_keys)}
    compiled_instructions = bytearray()
    for instruction in instructions:
        compiled_instructions.append(index[instruction.program_id])
        compiled_instructions += shortvec(len(instruction.accounts))
        for meta in instruction.accounts:
            compiled_instructions.append(index[meta.pubkey])
        compiled_instructions += shortvec(len(instruction.data))
        compiled_instructions += instruction.data

    message = (
        header
        + shortvec(len(account_keys))
        + b"".join(account_keys)
        + recent_blockhash
        + shortvec(len(instructions))
        + bytes(compiled_instructions)
    )
    return CompiledMessage(
        message_bytes=message,
        account_keys=account_keys,
        signer_keys=[m.pubkey for m in ordered if m.is_signer],
    )


def assemble_transaction(message_bytes: bytes, signatures: list[bytes]) -> bytes:
    """signatures (compact array) ‖ message — the wire transaction."""
    for signature in signatures:
        if len(signature) != 64:
            raise ValueError("Ed25519 signatures are 64 bytes")
    return shortvec(len(signatures)) + b"".join(signatures) + message_bytes


# ------------------------------------------------------------ instructions


def system_transfer(*, from_pubkey: bytes, to_pubkey: bytes, lamports: int) -> Instruction:
    """SystemProgram::Transfer (instruction index 2)."""
    if lamports <= 0:
        raise ValueError("lamports must be positive")
    return Instruction(
        program_id=keys.public_key_from_address(keys.SYSTEM_PROGRAM),
        accounts=(
            AccountMeta(from_pubkey, True, True),
            AccountMeta(to_pubkey, False, True),
        ),
        data=struct.pack("<I", 2) + struct.pack("<Q", lamports),
    )


def token_transfer_checked(
    *,
    source_ata: bytes,
    mint: bytes,
    destination_ata: bytes,
    owner: bytes,
    amount: int,
    decimals: int,
    token_program: bytes | None = None,
) -> Instruction:
    """SPL Token::TransferChecked (instruction index 12) — the mint
    and decimals travel with the call so a mismatched token account
    fails on-chain instead of silently moving value."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    return Instruction(
        program_id=token_program or keys.public_key_from_address(keys.TOKEN_PROGRAM),
        accounts=(
            AccountMeta(source_ata, False, True),
            AccountMeta(mint, False, False),
            AccountMeta(destination_ata, False, True),
            AccountMeta(owner, True, False),
        ),
        data=bytes([12]) + struct.pack("<Q", amount) + bytes([decimals]),
    )


def create_associated_token_account_idempotent(
    *, payer: bytes, ata: bytes, owner: bytes, mint: bytes, token_program: bytes | None = None
) -> Instruction:
    """Associated Token Program::CreateAssociatedTokenAccountIdempotent
    (instruction index 1) — succeeds whether or not the account
    already exists, so withdrawal construction never needs a
    separate existence probe for the destination."""
    token_program = token_program or keys.public_key_from_address(keys.TOKEN_PROGRAM)
    return Instruction(
        program_id=keys.public_key_from_address(keys.ASSOCIATED_TOKEN_PROGRAM),
        accounts=(
            AccountMeta(payer, True, True),
            AccountMeta(ata, False, True),
            AccountMeta(owner, False, False),
            AccountMeta(mint, False, False),
            AccountMeta(keys.public_key_from_address(keys.SYSTEM_PROGRAM), False, False),
            AccountMeta(token_program, False, False),
        ),
        data=bytes([1]),
    )
