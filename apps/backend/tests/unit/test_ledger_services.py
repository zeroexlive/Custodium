"""Ledger invariant tests — Phase 2 exit criteria (ADR 0007).

Covers: balanced double-entry, exact integer money (incl. wei-scale
magnitudes), idempotent replay + conflict detection, append-only
enforcement, the reserve -> settle/release flows with double-spend
protection, reversals, and the domain worked example (§11).
"""
from __future__ import annotations

import pytest
from django.core.management import call_command

from waas.modules.assets.models import Asset
from waas.modules.identity.models import User
from waas.modules.ledger import services
from waas.modules.ledger.models import (
    AccountType,
    JournalEntry,
    JournalLine,
)
from waas.modules.organizations.models import Organization
from waas.modules.projects.models import Project

pytestmark = pytest.mark.django_db


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    user = User.objects.create_user(email="ledger@example.com", password="x")
    org = Organization.objects.create(name="Ledger Org", slug="ledger-org")
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=user
    )
    usdt = Asset.objects.get(network__slug="ethereum", symbol="USDT")
    eth = Asset.objects.get(network__slug="ethereum", symbol="ETH")
    return {"user": user, "org": org, "project": project, "usdt": usdt, "eth": eth}


def account(ctx, asset, account_type, external_ref=""):
    return services.get_or_create_account(
        project=ctx["project"], asset=asset, account_type=account_type,
        external_ref=external_ref,
    )


def credit_deposit(ctx, asset, amount, key, customer="cust_1"):
    custody = account(ctx, asset, AccountType.CUSTODY_ONCHAIN)
    available = account(ctx, asset, AccountType.CUSTOMER_AVAILABLE, customer)
    return services.post_journal(
        project=ctx["project"], asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": custody, "side": "debit", "amount": amount},
            {"account": available, "side": "credit", "amount": amount},
        ],
        idempotency_key=key, operation_type="deposit", operation_id=key,
    )


def test_balanced_post_and_trial_balance(ctx) -> None:
    credit_deposit(ctx, ctx["usdt"], 100_000_000, "dep-1")
    available = account(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE, "cust_1")
    custody = account(ctx, ctx["usdt"], AccountType.CUSTODY_ONCHAIN)
    assert services.account_balance(available) == 100_000_000
    assert services.account_balance(custody) == 100_000_000
    assert services.trial_balance(ctx["project"], ctx["usdt"]) == 0


def test_unbalanced_and_single_sided_rejected(ctx) -> None:
    custody = account(ctx, ctx["usdt"], AccountType.CUSTODY_ONCHAIN)
    available = account(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE, "cust_1")
    with pytest.raises(services.UnbalancedEntryError):
        services.post_journal(
            project=ctx["project"], asset=ctx["usdt"], entry_type="deposit_credit",
            lines=[
                {"account": custody, "side": "debit", "amount": 100},
                {"account": available, "side": "credit", "amount": 99},
            ],
            idempotency_key="bad-1",
        )
    with pytest.raises(services.UnbalancedEntryError):
        services.post_journal(
            project=ctx["project"], asset=ctx["usdt"], entry_type="deposit_credit",
            lines=[{"account": custody, "side": "debit", "amount": 100}],
            idempotency_key="bad-2",
        )
    assert JournalEntry.objects.count() == 0


@pytest.mark.parametrize("bad_amount", [1.5, 100.0, True, "100", None, 0, -5])
def test_non_integer_or_non_positive_amounts_rejected(ctx, bad_amount) -> None:
    custody = account(ctx, ctx["usdt"], AccountType.CUSTODY_ONCHAIN)
    available = account(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE, "cust_1")
    with pytest.raises(services.InvalidAmountError):
        services.post_journal(
            project=ctx["project"], asset=ctx["usdt"], entry_type="deposit_credit",
            lines=[
                {"account": custody, "side": "debit", "amount": bad_amount},
                {"account": available, "side": "credit", "amount": bad_amount},
            ],
            idempotency_key=f"bad-amt-{bad_amount!r}",
        )


def test_wei_scale_amounts_are_exact(ctx) -> None:
    from django.db import connection

    if connection.vendor == "sqlite":
        # SQLite has no exact NUMERIC storage: values beyond int64 are
        # coerced to REAL, so >64-bit exactness cannot be demonstrated on
        # the SQLite test database. PostgreSQL NUMERIC(78,0) — the
        # production database — is exact by construction. The skip is
        # deliberate and recorded in AGENTS.md; a >32-bit amount that
        # fits int64 is still verified exactly below.
        amount = 999_999_999_999_999  # 10^15 - 1: exact under SQLite's Decimal adaptation
        credit_deposit(ctx, ctx["eth"], amount, "dep-wei")
        available = account(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE, "cust_1")
        assert services.account_balance(available) == amount
        pytest.skip("SQLite cannot store >int64 NUMERIC exactly; wei-scale case is PostgreSQL-only")
    amount = 2**70 + 12345  # beyond BIGINT range; NUMERIC(78,0) territory
    credit_deposit(ctx, ctx["eth"], amount, "dep-wei")
    available = account(ctx, ctx["eth"], AccountType.CUSTOMER_AVAILABLE, "cust_1")
    assert services.account_balance(available) == amount
    assert services.trial_balance(ctx["project"], ctx["eth"]) == 0


def test_idempotent_replay_and_conflict(ctx) -> None:
    entry, created = credit_deposit(ctx, ctx["usdt"], 500, "dep-dup")
    assert created is True
    replay, created = credit_deposit(ctx, ctx["usdt"], 500, "dep-dup")
    assert created is False
    assert replay.id == entry.id
    assert JournalEntry.objects.count() == 1
    assert JournalLine.objects.count() == 2
    with pytest.raises(services.IdempotencyConflictError):
        credit_deposit(ctx, ctx["usdt"], 501, "dep-dup")


def test_entries_and_lines_are_append_only(ctx) -> None:
    entry, _ = credit_deposit(ctx, ctx["usdt"], 500, "dep-immutable")
    entry.memo = "tampered"
    with pytest.raises(ValueError):
        entry.save()
    with pytest.raises(ValueError):
        entry.delete()
    line = entry.lines.first()
    with pytest.raises(ValueError):
        line.delete()


def test_reversal_nets_to_zero_and_is_single(ctx) -> None:
    entry, _ = credit_deposit(ctx, ctx["usdt"], 700, "dep-rev")
    reversal, created = services.reverse_entry(
        original=entry, reason="chain reorg", idempotency_key="rev-1"
    )
    assert created is True
    assert reversal.reverses_id == entry.id
    available = account(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE, "cust_1")
    assert services.account_balance(available) == 0
    assert services.trial_balance(ctx["project"], ctx["usdt"]) == 0
    again, created = services.reverse_entry(
        original=entry, reason="chain reorg", idempotency_key="rev-2"
    )
    assert created is False and again.id == reversal.id
    with pytest.raises(services.LedgerError):
        services.reverse_entry(original=reversal, reason="meta", idempotency_key="rev-3")
    with pytest.raises(services.LedgerError):
        services.reverse_entry(original=entry, reason="", idempotency_key="rev-4")


def test_reserve_settle_flow_and_double_spend_protection(ctx) -> None:
    credit_deposit(ctx, ctx["usdt"], 100, "dep-rs")
    reservation, created = services.reserve_funds(
        project=ctx["project"], asset=ctx["usdt"], external_ref="cust_1",
        amount=30, operation_type="withdrawal", operation_id="wd-1",
        idempotency_key="wd-1-reserve",
    )
    assert created is True
    available = account(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE, "cust_1")
    reserved = account(ctx, ctx["usdt"], AccountType.WITHDRAWAL_RESERVED, "cust_1")
    custody = account(ctx, ctx["usdt"], AccountType.CUSTODY_ONCHAIN)
    assert services.account_balance(available) == 70
    assert services.account_balance(reserved) == 30

    # The same funds cannot be reserved twice.
    with pytest.raises(services.InsufficientFundsError):
        services.reserve_funds(
            project=ctx["project"], asset=ctx["usdt"], external_ref="cust_1",
            amount=71, operation_type="withdrawal", operation_id="wd-2",
            idempotency_key="wd-2-reserve",
        )
    # Idempotent replay of the first reservation returns it unchanged.
    replay, created = services.reserve_funds(
        project=ctx["project"], asset=ctx["usdt"], external_ref="cust_1",
        amount=30, operation_type="withdrawal", operation_id="wd-1",
        idempotency_key="wd-1-reserve",
    )
    assert created is False and replay.id == reservation.id

    settled, _ = services.settle_reservation(
        reservation=reservation, idempotency_key="wd-1-settle"
    )
    assert settled.state == "consumed"
    assert services.account_balance(reserved) == 0
    assert services.account_balance(custody) == 70
    assert services.account_balance(available) == 70
    assert services.trial_balance(ctx["project"], ctx["usdt"]) == 0
    with pytest.raises(services.ReservationStateError):
        services.release_reservation(reservation=settled, idempotency_key="wd-1-release")


def test_reserve_release_restores_available(ctx) -> None:
    credit_deposit(ctx, ctx["usdt"], 50, "dep-rel")
    reservation, _ = services.reserve_funds(
        project=ctx["project"], asset=ctx["usdt"], external_ref="cust_1",
        amount=50, operation_type="withdrawal", operation_id="wd-9",
        idempotency_key="wd-9-reserve",
    )
    released, _ = services.release_reservation(
        reservation=reservation, idempotency_key="wd-9-release"
    )
    assert released.state == "released"
    available = account(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE, "cust_1")
    assert services.account_balance(available) == 50


def test_domain_worked_example(ctx) -> None:
    """docs/domain/ledger-design.md §11: deposit 100, withdraw 30, sweep 50."""
    usdt = ctx["usdt"]
    credit_deposit(ctx, usdt, 100_000_000, "ex-dep")
    reservation, _ = services.reserve_funds(
        project=ctx["project"], asset=usdt, external_ref="cust_1",
        amount=30_000_000, operation_type="withdrawal", operation_id="ex-wd",
        idempotency_key="ex-wd-reserve",
    )
    services.settle_reservation(reservation=reservation, idempotency_key="ex-wd-settle")
    custody = account(ctx, usdt, AccountType.CUSTODY_ONCHAIN)
    swept = account(ctx, usdt, AccountType.SWEPT_OUT)
    services.post_journal(
        project=ctx["project"], asset=usdt, entry_type=JournalEntry.EntryType.SWEEP,
        lines=[
            {"account": swept, "side": "debit", "amount": 50_000_000},
            {"account": custody, "side": "credit", "amount": 50_000_000},
        ],
        idempotency_key="ex-sweep", operation_type="sweep", operation_id="ex-sweep",
    )
    available = account(ctx, usdt, AccountType.CUSTOMER_AVAILABLE, "cust_1")
    # The sweep moved coins, not customer claims: still exactly 70 USDT.
    assert services.account_balance(available) == 70_000_000
    assert services.account_balance(custody) == 20_000_000
    assert services.account_balance(swept) == 50_000_000
    assert services.trial_balance(ctx["project"], usdt) == 0
