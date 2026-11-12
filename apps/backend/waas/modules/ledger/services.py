"""The ledger service — the ONLY writer of journal entries (ADR 0007).

Guarantees enforced here, transactionally:
- balanced entries: sum(debits) == sum(credits) per entry (single asset);
- exact integer amounts (int only; bools/floats/strings rejected);
- idempotency: same key + same payload returns the existing entry;
  same key + different payload is a conflict;
- reservations check funds under a row lock, so the same funds cannot
  be reserved twice;
- reversals append a negating entry linked to the original.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from waas.modules.assets.models import Asset
from waas.modules.ledger.models import (
    NORMAL_SIDE,
    AccountType,
    BalanceReservation,
    JournalEntry,
    JournalLine,
    LedgerAccount,
)
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet


class LedgerError(Exception):
    """Base class for ledger domain errors."""


class InvalidAmountError(LedgerError):
    pass


class UnbalancedEntryError(LedgerError):
    pass


class IdempotencyConflictError(LedgerError):
    pass


class InsufficientFundsError(LedgerError):
    pass


class ReservationStateError(LedgerError):
    pass


def validate_amount(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidAmountError("Amounts must be exact integers in base units")
    if value <= 0:
        raise InvalidAmountError("Amounts must be positive")
    return value


def get_or_create_account(
    *,
    project: Project,
    asset: Asset,
    account_type: str,
    wallet: Wallet | None = None,
    external_ref: str = "",
) -> LedgerAccount:
    if account_type not in AccountType.values:
        raise LedgerError(f"Unknown account type '{account_type}'")
    if asset.network_id is None:
        raise LedgerError("Asset must be persisted")
    scope_key = f"{wallet.id if wallet else '-'}:{external_ref}"
    account, _ = LedgerAccount.objects.get_or_create(
        project=project,
        asset=asset,
        account_type=account_type,
        scope_key=scope_key,
        defaults={"wallet": wallet, "external_ref": external_ref},
    )
    return account


def _payload_hash(entry_type: str, lines: list[dict], reverses_id: str | None) -> str:
    canonical = {
        "entry_type": entry_type,
        "reverses": reverses_id,
        "lines": sorted(
            (str(line["account"].id), line["side"], line["amount"]) for line in lines
        ),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def _lock_accounts(accounts: list[LedgerAccount]) -> None:
    # Deterministic lock order prevents deadlocks between concurrent posts.
    ids = sorted({a.id for a in accounts})
    list(LedgerAccount.objects.select_for_update().filter(id__in=ids))


@transaction.atomic
def post_journal(
    *,
    project: Project,
    asset: Asset,
    entry_type: str,
    lines: list[dict],
    idempotency_key: str,
    operation_type: str = "",
    operation_id: str = "",
    actor_type: str = "system",
    actor_id: str = "",
    memo: str = "",
    reason: str = "",
    reverses: JournalEntry | None = None,
) -> tuple[JournalEntry, bool]:
    """Post one balanced journal entry. Returns (entry, created)."""
    if entry_type not in JournalEntry.EntryType.values:
        raise LedgerError(f"Unknown entry type '{entry_type}'")
    if entry_type == JournalEntry.EntryType.REVERSAL and (reverses is None or not reason):
        raise LedgerError("Reversal entries require a target entry and a reason")
    if entry_type == JournalEntry.EntryType.ADJUSTMENT and not reason:
        raise LedgerError("Manual adjustments require a reason")
    if not lines:
        raise UnbalancedEntryError("A journal entry needs at least one debit and one credit line")

    normalised: list[dict] = []
    total_debits = 0
    total_credits = 0
    for line in lines:
        account = line["account"]
        side = line["side"]
        amount = validate_amount(line["amount"])
        if not isinstance(account, LedgerAccount):
            raise LedgerError("Lines must reference LedgerAccount instances")
        if account.project_id != project.id or account.asset_id != asset.id:
            raise LedgerError("All lines must belong to the entry's project and asset")
        if side not in JournalLine.Side.values:
            raise LedgerError(f"Unknown line side '{side}'")
        if side == JournalLine.Side.DEBIT:
            total_debits += amount
        else:
            total_credits += amount
        normalised.append({"account": account, "side": side, "amount": amount})
    if total_debits == 0 or total_credits == 0 or total_debits != total_credits:
        raise UnbalancedEntryError(
            f"Entry is not balanced: debits={total_debits} credits={total_credits}"
        )

    payload_hash = _payload_hash(entry_type, normalised, str(reverses.id) if reverses else None)
    existing = JournalEntry.objects.filter(
        project=project, idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise IdempotencyConflictError(
                f"Idempotency key '{idempotency_key}' was already used with a different payload"
            )
        return existing, False

    _lock_accounts([line["account"] for line in normalised])
    try:
        entry = JournalEntry.objects.create(
            project=project,
            asset=asset,
            entry_type=entry_type,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            operation_type=operation_type,
            operation_id=operation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            memo=memo,
            reason=reason,
            reverses=reverses,
        )
    except IntegrityError:
        # A concurrent post with the same key won the race; treat as replay.
        existing = JournalEntry.objects.get(project=project, idempotency_key=idempotency_key)
        if existing.payload_hash != payload_hash:
            raise IdempotencyConflictError(
                f"Idempotency key '{idempotency_key}' was already used with a different payload"
            ) from None
        return existing, False
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                entry=entry, account=line["account"], side=line["side"],
                amount=Decimal(line["amount"]),
            )
            for line in normalised
        ]
    )
    return entry, True


def raw_balance(account: LedgerAccount) -> int:
    """Debits minus credits (trial-balance terms)."""
    totals = account.lines.values("side").annotate(total=Sum("amount"))
    debits = credits = 0
    for row in totals:
        if row["side"] == JournalLine.Side.DEBIT:
            debits = int(row["total"])
        else:
            credits = int(row["total"])
    return debits - credits


def account_balance(account: LedgerAccount) -> int:
    """Balance in the account's normal terms (positive = normal holding)."""
    raw = raw_balance(account)
    return raw if NORMAL_SIDE[account.account_type] == "debit" else -raw


def trial_balance(project: Project, asset: Asset) -> int:
    """Must always be exactly 0 for a correct double-entry ledger."""
    return sum(
        raw_balance(account)
        for account in LedgerAccount.objects.filter(project=project, asset=asset)
    )


@transaction.atomic
def reserve_funds(
    *,
    project: Project,
    asset: Asset,
    external_ref: str,
    amount: int,
    operation_type: str,
    operation_id: str,
    idempotency_key: str,
    actor_type: str = "system",
    actor_id: str = "",
    expires_at=None,
) -> tuple[BalanceReservation, bool]:
    """Move funds customer_available -> withdrawal_reserved, with a hold record.

    The availability check and the posting happen under the account row
    lock, so concurrent reservations cannot spend the same funds twice.
    """
    amount = validate_amount(amount)
    existing_entry = JournalEntry.objects.filter(
        project=project, idempotency_key=idempotency_key
    ).first()
    if existing_entry is not None:
        reservation = existing_entry.reservations_created.first()
        if reservation is None:
            raise IdempotencyConflictError(
                f"Idempotency key '{idempotency_key}' belongs to a non-reservation entry"
            )
        return reservation, False

    available_account = get_or_create_account(
        project=project, asset=asset,
        account_type=AccountType.CUSTOMER_AVAILABLE, external_ref=external_ref,
    )
    reserved_account = get_or_create_account(
        project=project, asset=asset,
        account_type=AccountType.WITHDRAWAL_RESERVED, external_ref=external_ref,
    )
    _lock_accounts([available_account, reserved_account])
    # Re-check after locking: another transaction may have posted meanwhile.
    existing_entry = JournalEntry.objects.filter(
        project=project, idempotency_key=idempotency_key
    ).first()
    if existing_entry is not None:
        reservation = existing_entry.reservations_created.first()
        if reservation is None:
            raise IdempotencyConflictError(
                f"Idempotency key '{idempotency_key}' belongs to a non-reservation entry"
            )
        return reservation, False
    if account_balance(available_account) < amount:
        raise InsufficientFundsError(
            f"Available balance {account_balance(available_account)} is below reservation {amount}"
        )
    entry, _ = post_journal(
        project=project, asset=asset,
        entry_type=JournalEntry.EntryType.WITHDRAWAL_RESERVATION,
        lines=[
            {"account": available_account, "side": JournalLine.Side.DEBIT, "amount": amount},
            {"account": reserved_account, "side": JournalLine.Side.CREDIT, "amount": amount},
        ],
        idempotency_key=idempotency_key,
        operation_type=operation_type, operation_id=operation_id,
        actor_type=actor_type, actor_id=actor_id,
    )
    reservation = BalanceReservation.objects.create(
        project=project, asset=asset, account=available_account,
        amount=Decimal(amount), operation_type=operation_type,
        operation_id=operation_id, journal_entry=entry, expires_at=expires_at,
    )
    return reservation, True


def _close_reservation(
    *,
    reservation: BalanceReservation,
    settle: bool,
    idempotency_key: str,
    actor_type: str,
    actor_id: str,
) -> tuple[BalanceReservation, bool]:
    with transaction.atomic():
        locked = BalanceReservation.objects.select_for_update().get(pk=reservation.pk)
        if locked.state != BalanceReservation.State.ACTIVE:
            if locked.closing_entry and locked.closing_entry.idempotency_key == idempotency_key:
                return locked, False
            raise ReservationStateError(
                f"Reservation {locked.id} is already {locked.state}"
            )
        if locked.expires_at and locked.expires_at < timezone.now():
            raise ReservationStateError(f"Reservation {locked.id} has expired")
        project, asset = locked.project, locked.asset
        external_ref = locked.account.external_ref
        amount = int(locked.amount)
        reserved_account = get_or_create_account(
            project=project, asset=asset,
            account_type=AccountType.WITHDRAWAL_RESERVED, external_ref=external_ref,
        )
        if settle:
            target = get_or_create_account(
                project=project, asset=asset, account_type=AccountType.CUSTODY_ONCHAIN,
                wallet=None, external_ref="",
            )
            entry_type = JournalEntry.EntryType.WITHDRAWAL_SETTLEMENT
            new_state = BalanceReservation.State.CONSUMED
        else:
            target = locked.account  # back to customer_available
            entry_type = JournalEntry.EntryType.WITHDRAWAL_RELEASE
            new_state = BalanceReservation.State.RELEASED
        entry, _ = post_journal(
            project=project, asset=asset, entry_type=entry_type,
            lines=[
                {"account": reserved_account, "side": JournalLine.Side.DEBIT, "amount": amount},
                {"account": target, "side": JournalLine.Side.CREDIT, "amount": amount},
            ],
            idempotency_key=idempotency_key,
            operation_type=locked.operation_type, operation_id=locked.operation_id,
            actor_type=actor_type, actor_id=actor_id,
        )
        locked.state = new_state
        locked.closing_entry = entry
        locked.save(update_fields=["state", "closing_entry", "updated_at"])
        return locked, True


def settle_reservation(
    *, reservation: BalanceReservation, idempotency_key: str,
    actor_type: str = "system", actor_id: str = "",
) -> tuple[BalanceReservation, bool]:
    """Settle: reserved funds leave custody (Dr reserved / Cr custody_onchain)."""
    return _close_reservation(
        reservation=reservation, settle=True, idempotency_key=idempotency_key,
        actor_type=actor_type, actor_id=actor_id,
    )


def release_reservation(
    *, reservation: BalanceReservation, idempotency_key: str,
    actor_type: str = "system", actor_id: str = "",
) -> tuple[BalanceReservation, bool]:
    """Release: reserved funds return to available (Dr reserved / Cr available)."""
    return _close_reservation(
        reservation=reservation, settle=False, idempotency_key=idempotency_key,
        actor_type=actor_type, actor_id=actor_id,
    )


@transaction.atomic
def reverse_entry(
    *,
    original: JournalEntry,
    reason: str,
    idempotency_key: str,
    actor_type: str = "system",
    actor_id: str = "",
) -> tuple[JournalEntry, bool]:
    """Append a negating entry for ``original``; the pair nets to zero."""
    if not reason:
        raise LedgerError("Reversals require a reason")
    if original.entry_type == JournalEntry.EntryType.REVERSAL:
        raise LedgerError("A reversal entry cannot itself be reversed")
    existing = JournalEntry.objects.filter(reverses=original).first()
    if existing is not None:
        return existing, False
    lines = [
        {
            "account": line.account,
            "side": (
                JournalLine.Side.CREDIT
                if line.side == JournalLine.Side.DEBIT
                else JournalLine.Side.DEBIT
            ),
            "amount": int(line.amount),
        }
        for line in original.lines.select_related("account").all()
    ]
    return post_journal(
        project=original.project, asset=original.asset,
        entry_type=JournalEntry.EntryType.REVERSAL,
        lines=lines, idempotency_key=idempotency_key,
        operation_type=original.operation_type, operation_id=original.operation_id,
        actor_type=actor_type, actor_id=actor_id, reason=reason, reverses=original,
    )
