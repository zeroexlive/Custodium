"""Phase 12 hardening: DB-level append-only triggers, the
platform kill switch, and health/readiness probes."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import Client

from tests.conftest import auth_headers, register_user
from waas.modules.assets.models import Asset
from waas.modules.audit.models import AuditEvent
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.operations import services as op_services
from waas.modules.operations.models import PlatformHalt
from waas.modules.organizations.models import Membership, Organization
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet

pytestmark = pytest.mark.django_db


def _raw(sql: str, params: tuple = ()) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def test_append_only_triggers_installed_and_enforced() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
        triggers = {row[0] for row in cursor.fetchall()}
    for table in (
        "ledger_journal_entry", "ledger_journal_line", "audit_audit_event",
        "sweeps_resolveddestinationsnapshot",
    ):
        assert f"{table}_no_update" in triggers
        assert f"{table}_no_delete" in triggers

    call_command("seed_networks_assets")
    User = get_user_model()
    org = Organization.objects.create(name="Trig Org", slug="trig-org")
    user = User.objects.create_user(email="trig@example.com", password="x" * 12)
    Membership.objects.create(organization=org, user=user, role=Membership.Role.OWNER)
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=user
    )
    network = BlockchainNetwork.objects.get(slug="ethereum")
    asset = Asset.objects.get(network=network, symbol="USDT")
    entry, _ = ledger_services.post_journal(
        project=project, asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset, account_type=AccountType.CUSTODY_ONCHAIN),
             "side": "debit", "amount": 10},
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset, account_type=AccountType.CUSTOMER_AVAILABLE),
             "side": "credit", "amount": 10},
        ],
        idempotency_key="trig:1", operation_type="deposit", operation_id="t1",
    )
    event = AuditEvent.record("trig.test", actor_user=user, organization=org)
    # Raw SQL cannot rewrite the journal or the audit trail.
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            _raw("UPDATE ledger_journal_entry SET memo='x' WHERE id=%s", (entry.id.hex,))
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            _raw("DELETE FROM ledger_journal_line WHERE entry_id=%s", (entry.id.hex,))
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            _raw("UPDATE audit_audit_event SET event_type='forged' WHERE id=%s", (event.id.hex,))
    # …but appends (the only legitimate write) still work.
    assert ledger_services.trial_balance(project=project, asset=asset) == 0


@pytest.fixture()
def halt_ctx():
    call_command("seed_networks_assets")
    User = get_user_model()
    org = Organization.objects.create(name="Halt Org", slug="halt-org")
    owner = User.objects.create_user(email="halt@example.com", password="x" * 12)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=owner
    )
    network = BlockchainNetwork.objects.get(slug="ethereum")
    asset = Asset.objects.get(network=network, symbol="USDT")
    wallet = Wallet.objects.create(project=project, label="ops", external_customer_id="c1")
    return {"org": org, "owner": owner, "project": project,
            "network": network, "asset": asset, "wallet": wallet}


def test_platform_halt_blocks_money_movement(halt_ctx) -> None:
    PlatformHalt.objects.create(pk=1, active=True, reason="incident drill")
    with pytest.raises(op_services.OperationsError):
        op_services.create_withdrawal_request(
            wallet=halt_ctx["wallet"], network=halt_ctx["network"],
            asset=halt_ctx["asset"],
            destination_address="0x3535353535353535353535353535353535353535",
            amount=100, idempotency_key="halt-1",
        )
    from waas.modules.sweeps import services as sweep_services

    with pytest.raises(sweep_services.SweepError):
        sweep_services.create_sweep(
            wallet=halt_ctx["wallet"], network=halt_ctx["network"],
            asset=halt_ctx["asset"], idempotency_key="halt-2",
        )
    PlatformHalt.objects.filter(pk=1).update(active=False)
    request = op_services.create_withdrawal_request(
        wallet=halt_ctx["wallet"], network=halt_ctx["network"],
        asset=halt_ctx["asset"],
        destination_address="0x3535353535353535353535353535353535353535",
        amount=100, idempotency_key="halt-3",
    )
    assert request.id is not None


def test_operator_halt_api_is_staff_only() -> None:
    client = Client()
    plain = register_user(client, "plain@example.com")
    denied = client.get(
        "/api/v1/operator/platform-halt", **auth_headers(plain["access_token"])
    )
    assert denied.status_code == 403
    User = get_user_model()
    staff = User.objects.get(email="plain@example.com")
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    no_reason = client.post(
        "/api/v1/operator/platform-halt",
        data='{"active": true, "reason": ""}',
        content_type="application/json",
        **auth_headers(plain["access_token"]),
    )
    assert no_reason.status_code == 422
    ok = client.post(
        "/api/v1/operator/platform-halt",
        data='{"active": true, "reason": "drill"}',
        content_type="application/json",
        **auth_headers(plain["access_token"]),
    )
    assert ok.status_code == 200, ok.content[:200]
    assert PlatformHalt.is_active()
    assert AuditEvent.objects.filter(event_type="operator.platform_halt_changed").exists()


def test_health_and_readiness_probes() -> None:
    client = Client()
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
