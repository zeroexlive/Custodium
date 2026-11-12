"""Double-entry, append-only ledger (ADR 0007, docs/domain/ledger-design.md).

Amounts are exact integers in asset base units, stored in a
NUMERIC(78,0) column so wei-scale magnitudes never overflow. Floats are
forbidden anywhere in this module. Posted journal entries and lines are
immutable at the model layer: corrections are reversal entries, never
UPDATEs or DELETEs (database-trigger enforcement is Phase 12 hardening).
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class AccountType(models.TextChoices):
    """Chart of accounts (docs/domain/ledger-design.md §4)."""

    CUSTODY_ONCHAIN = "custody_onchain", "Custody — on-chain"
    CUSTODY_PENDING = "custody_pending", "Custody — pending deposits"
    CUSTOMER_AVAILABLE = "customer_available", "Customer — available"
    CUSTOMER_PENDING = "customer_pending", "Customer — pending"
    WITHDRAWAL_RESERVED = "withdrawal_reserved", "Withdrawal — reserved"
    TREASURY_AVAILABLE = "treasury_available", "Treasury — available"
    SWEPT_OUT = "swept_out", "Swept out of custody"
    NETWORK_FEES = "network_fees", "Network fees"
    PLATFORM_FEES_PAYABLE = "platform_fees_payable", "Platform fees payable"
    SUSPENSE = "suspense", "Suspense (must clear to zero)"


# Normal balance side per account type. Balances are reported in normal
# terms; the raw trial balance (debits - credits over ALL accounts of a
# project+asset) is always exactly zero.
NORMAL_SIDE = {
    AccountType.CUSTODY_ONCHAIN: "debit",
    AccountType.CUSTODY_PENDING: "debit",
    AccountType.CUSTOMER_AVAILABLE: "credit",
    AccountType.CUSTOMER_PENDING: "credit",
    AccountType.WITHDRAWAL_RESERVED: "credit",
    AccountType.TREASURY_AVAILABLE: "credit",
    AccountType.SWEPT_OUT: "debit",
    AccountType.NETWORK_FEES: "debit",
    AccountType.PLATFORM_FEES_PAYABLE: "credit",
    AccountType.SUSPENSE: "debit",
}


class LedgerAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="ledger_accounts"
    )
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.PROTECT, related_name="ledger_accounts"
    )
    wallet = models.ForeignKey(
        "wallets.Wallet", on_delete=models.PROTECT, null=True, blank=True,
        related_name="ledger_accounts",
    )
    # Customer/tenant sub-scope within the project ("" = project-level).
    external_ref = models.CharField(max_length=128, blank=True, default="")
    account_type = models.CharField(max_length=32, choices=AccountType.choices)
    # Deterministic uniqueness scope (wallet id or "-") + external_ref.
    scope_key = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "ledger_account"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "asset", "account_type", "scope_key"],
                name="uniq_ledger_account_scope",
            )
        ]

    def __str__(self) -> str:
        return f"LedgerAccount({self.account_type}, asset={self.asset_id}, scope={self.scope_key})"


class ImmutableModel(models.Model):
    """Append-only base: rows can be created but never updated or deleted."""

    class Meta:
        abstract = True

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ValueError(f"{type(self).__name__} rows are append-only and cannot be modified")
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValueError(f"{type(self).__name__} rows are append-only and cannot be deleted")


class JournalEntry(ImmutableModel):
    class EntryType(models.TextChoices):
        DEPOSIT_OBSERVED = "deposit_observed", "Deposit observed (pre-finality)"
        DEPOSIT_CREDIT = "deposit_credit", "Deposit credited"
        WITHDRAWAL_RESERVATION = "withdrawal_reservation", "Withdrawal reservation"
        WITHDRAWAL_SETTLEMENT = "withdrawal_settlement", "Withdrawal settlement"
        WITHDRAWAL_RELEASE = "withdrawal_release", "Withdrawal reservation release"
        SWEEP = "sweep", "Sweep"
        FEE = "fee", "Fee"
        REVERSAL = "reversal", "Reversal"
        ADJUSTMENT = "adjustment", "Manual adjustment"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="journal_entries"
    )
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.PROTECT, related_name="journal_entries"
    )
    entry_type = models.CharField(max_length=32, choices=EntryType.choices)
    idempotency_key = models.CharField(max_length=200)
    # Canonical hash of the posting payload, so an idempotency replay with
    # DIFFERENT lines is a conflict, not a silent success.
    payload_hash = models.CharField(max_length=64)
    operation_type = models.CharField(max_length=64, blank=True, default="")
    operation_id = models.CharField(max_length=128, blank=True, default="")
    actor_type = models.CharField(max_length=32, default="system")
    actor_id = models.CharField(max_length=128, blank=True, default="")
    memo = models.CharField(max_length=500, blank=True, default="")
    reason = models.CharField(max_length=500, blank=True, default="")
    reverses = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_by"
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "ledger_journal_entry"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "idempotency_key"], name="uniq_journal_project_idempotency"
            )
        ]

    def __str__(self) -> str:
        return f"JournalEntry({self.entry_type}, key={self.idempotency_key})"


class JournalLine(ImmutableModel):
    class Side(models.TextChoices):
        DEBIT = "debit", "Debit"
        CREDIT = "credit", "Credit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="lines")
    side = models.CharField(max_length=8, choices=Side.choices)
    # Exact integer base units. NUMERIC(78,0): no float, no 64-bit overflow.
    amount = models.DecimalField(max_digits=78, decimal_places=0)

    class Meta:
        db_table = "ledger_journal_line"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="journal_line_amount_positive")
        ]

    def __str__(self) -> str:
        return f"JournalLine({self.side} {self.amount} -> account {self.account_id})"


class BalanceReservation(models.Model):
    """Lifecycle record for journal-backed reservations (ADR 0007 §4).

    The reservation's funds movement is a real journal entry
    (Dr customer_available / Cr withdrawal_reserved); this row tracks the
    operation linkage and one-way state machine:
    active -> consumed | released | expired.
    """

    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        CONSUMED = "consumed", "Consumed (settled)"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="balance_reservations"
    )
    asset = models.ForeignKey(
        "assets.Asset", on_delete=models.PROTECT, related_name="balance_reservations"
    )
    account = models.ForeignKey(
        LedgerAccount, on_delete=models.PROTECT, related_name="reservations"
    )
    amount = models.DecimalField(max_digits=78, decimal_places=0)
    operation_type = models.CharField(max_length=64, blank=True, default="")
    operation_id = models.CharField(max_length=128, blank=True, default="")
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    journal_entry = models.ForeignKey(
        JournalEntry, on_delete=models.PROTECT, related_name="reservations_created"
    )
    closing_entry = models.ForeignKey(
        JournalEntry, on_delete=models.PROTECT, null=True, blank=True,
        related_name="reservations_closed",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ledger_balance_reservation"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="reservation_amount_positive")
        ]

    def __str__(self) -> str:
        return f"BalanceReservation({self.id}, {self.state}, {self.amount})"
