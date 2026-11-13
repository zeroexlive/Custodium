"""Feature-gap closures (post-roadmap audit): TOTP two-factor
auth, API-key IP allowlist/expiry options, the destination
address book + withdrawal allowlist, webhook secret rotation,
and auto-sweep rules.

Fixtures follow the operations/sweeps pattern: ORM-built org /
project / wallet with a real ledger credit.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from tests.conftest import PASSWORD, auth_headers, hmac_headers, register_user
from waas.modules.assets.models import Asset
from waas.modules.identity.models import DashboardToken
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.operations import services as ops_services
from waas.modules.organizations.models import Membership, Organization
from waas.modules.projects.models import Project
from waas.modules.sweeps import services as sweep_services
from waas.modules.sweeps.models import AutoSweepRule, Sweep
from waas.modules.wallets import services as wallet_services
from waas.modules.wallets.models import Wallet
from waas.modules.webhooks import services as webhook_services
from waas.security.secret_management.crypto import decrypt_secret

FROM = "0x9d8A62f656a8d1615C1294fd71e9CFb3E4855A4F"
DEST = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"
PUBLIC_DNS = lambda host: ["93.184.216.34"]  # noqa: E731


@pytest.fixture()
def ctx(db):
    call_command("seed_networks_assets")
    User = get_user_model()
    org = Organization.objects.create(name="Gap Org", slug="gap-org")
    owner = User.objects.create_user(email="g-owner@example.com", password=PASSWORD)
    viewer = User.objects.create_user(email="g-view@example.com", password=PASSWORD)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    Membership.objects.create(organization=org, user=viewer, role=Membership.Role.VIEWER)
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=owner
    )
    network = BlockchainNetwork.objects.get(slug="ethereum")
    asset = Asset.objects.get(network=network, symbol="USDT")
    wallet = Wallet.objects.create(project=project, label="ops", external_customer_id="cust_1")
    wallet_services.record_derived_address(
        wallet=wallet, network=network, address=FROM, derivation_path="custodium/evm/1"
    )
    ledger_services.post_journal(
        project=project, asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset, account_type=AccountType.CUSTODY_ONCHAIN),
             "side": "debit", "amount": 1_000_000},
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset,
                account_type=AccountType.CUSTOMER_AVAILABLE, external_ref="cust_1"),
             "side": "credit", "amount": 1_000_000},
        ],
        idempotency_key="seed:gaps", operation_type="deposit", operation_id="seed",
    )
    _, owner_token = DashboardToken.issue(owner)
    _, viewer_token = DashboardToken.issue(viewer)
    return {
        "org": org, "project": project, "network": network, "asset": asset,
        "wallet": wallet, "owner": owner, "viewer": viewer,
        "owner_token": owner_token, "viewer_token": viewer_token,
    }


def post(client: Client, path: str, token: str, payload: dict, method="post"):
    return getattr(client, method)(
        path, data=json.dumps(payload), content_type="application/json",
        **auth_headers(token),
    )


@pytest.mark.django_db
class TestTotp:
    def _enable(self, client: Client, token: str) -> tuple[str, list[str]]:
        setup = post(client, "/api/v1/auth/2fa/setup", token, {})
        assert setup.status_code == 200, setup.content
        secret = setup.json()["secret"]
        assert setup.json()["provisioning_uri"].startswith("otpauth://totp/")
        code = pyotp.TOTP(secret).now()
        enable = post(client, "/api/v1/auth/2fa/enable", token, {"code": code})
        assert enable.status_code == 200, enable.content
        return secret, enable.json()["recovery_codes"]

    def test_full_challenge_flow(self, client: Client):
        user = register_user(client, "totp@example.com")
        secret, _ = self._enable(client, user["token"])
        # Login now pauses at the challenge: no session token yet.
        login = post(client, "/api/v1/auth/login", "", {
            "email": "totp@example.com", "password": PASSWORD})
        assert login.status_code == 200
        body = login.json()
        assert body["requires_totp"] is True and body["token"] is None
        assert body["user"]["totp_enabled"] is True
        # Wrong code rejected.
        bad = post(client, "/api/v1/auth/2fa/verify", "", {
            "mfa_token": body["mfa_token"], "code": "000000"})
        assert bad.status_code == 401
        # Right code completes the login.
        done = post(client, "/api/v1/auth/2fa/verify", "", {
            "mfa_token": body["mfa_token"], "code": pyotp.TOTP(secret).now()})
        assert done.status_code == 200, done.content
        assert done.json()["token"]
        me = client.get("/api/v1/me", **auth_headers(done.json()["token"]))
        assert me.json()["totp_enabled"] is True

    def test_recovery_code_is_single_use(self, client: Client):
        user = register_user(client, "totp-rec@example.com")
        _, codes = self._enable(client, user["token"])

        def login_with(code: str):
            login = post(client, "/api/v1/auth/login", "", {
                "email": "totp-rec@example.com", "password": PASSWORD})
            return post(client, "/api/v1/auth/2fa/verify", "", {
                "mfa_token": login.json()["mfa_token"], "code": code})

        assert login_with(codes[0]).status_code == 200
        assert login_with(codes[0]).status_code == 401  # consumed
        assert login_with(codes[1]).status_code == 200  # next one works

    def test_enable_requires_valid_code_and_disable_restores_password_only(
        self, client: Client
    ):
        user = register_user(client, "totp-dis@example.com")
        setup = post(client, "/api/v1/auth/2fa/setup", user["token"], {})
        secret = setup.json()["secret"]
        bad = post(client, "/api/v1/auth/2fa/enable", user["token"], {"code": "000000"})
        assert bad.status_code == 422
        good = post(client, "/api/v1/auth/2fa/enable", user["token"],
                    {"code": pyotp.TOTP(secret).now()})
        assert good.status_code == 200
        # Second setup while enabled is refused.
        again = post(client, "/api/v1/auth/2fa/setup", user["token"], {})
        assert again.status_code == 409
        disable = post(client, "/api/v1/auth/2fa/disable", user["token"],
                       {"code": pyotp.TOTP(secret).now()})
        assert disable.status_code == 200
        login = post(client, "/api/v1/auth/login", "", {
            "email": "totp-dis@example.com", "password": PASSWORD})
        assert login.json()["requires_totp"] is False
        assert login.json()["token"]


@pytest.mark.django_db
class TestApiKeyHardeningOptions:
    @pytest.fixture()
    def flow(self, client: Client):
        from tests.conftest import make_org_project

        user = register_user(client, "apikey@example.com")
        ids = make_org_project(client, user["token"])
        return {"token": user["token"], "project_id": ids["project"]["id"]}

    def _create_key(self, client: Client, flow, **extra) -> dict:
        payload = {
            "project_id": flow["project_id"], "name": "ci",
            "scopes": ["read"], **extra,
        }
        resp = post(client, "/api/v1/api-keys", flow["token"], payload)
        assert resp.status_code == 201, resp.content
        return resp.json()

    def _whoami(self, client: Client, key: dict) -> int:
        path = "/api/v1/machine/whoami"
        resp = client.get(path, **hmac_headers(key["secret"], key["key_id"], "GET", path))
        return resp.status_code

    def test_ip_allowlist_enforced(self, client: Client, flow):
        blocked = self._create_key(client, flow, ip_allowlist=["10.9.9.9"])
        assert blocked["ip_allowlist"] == ["10.9.9.9"]
        assert self._whoami(client, blocked) in (401, 403)
        # The test client originates from 127.0.0.1.
        allowed = self._create_key(client, flow, ip_allowlist=["127.0.0.1"])
        assert self._whoami(client, allowed) == 200

    def test_expiry_enforced(self, client: Client, flow):
        past = (timezone.now() - timedelta(minutes=5)).isoformat()
        expired = self._create_key(client, flow, expires_at=past)
        assert self._whoami(client, expired) in (401, 403)
        future = (timezone.now() + timedelta(days=30)).isoformat()
        valid = self._create_key(client, flow, expires_at=future)
        assert self._whoami(client, valid) == 200


@pytest.mark.django_db
class TestAddressBook:
    def _add(self, client: Client, ctx, token: str, address: str = DEST):
        return post(client, "/api/v1/address-book", token, {
            "project_id": str(ctx["project"].id), "network": "ethereum",
            "address": address, "label": "exchange hot wallet",
        })

    def _withdraw(self, ctx, destination: str, key: str):
        return ops_services.create_withdrawal_request(
            wallet=ctx["wallet"], network=ctx["network"], asset=ctx["asset"],
            destination_address=destination, amount=100_000, idempotency_key=key,
        )

    def test_crud_and_uniqueness(self, client: Client, ctx):
        created = self._add(client, ctx, ctx["owner_token"])
        assert created.status_code == 201, created.content
        assert created.json()["network"] == "ethereum"
        # Same address in a different case still collides (matching
        # is on the normalized form).
        mixed = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
        assert self._add(client, ctx, ctx["owner_token"], mixed).status_code == 201
        duplicate = self._add(client, ctx, ctx["owner_token"], mixed.upper().replace("0X", "0x"))
        assert duplicate.status_code == 409
        invalid = self._add(client, ctx, ctx["owner_token"], "not-an-address")
        assert invalid.status_code == 422
        listing = client.get(
            f"/api/v1/address-book?project_id={ctx['project'].id}",
            **auth_headers(ctx["viewer_token"]),
        )
        assert listing.status_code == 200 and len(listing.json()["items"]) == 2
        removed = client.delete(
            f"/api/v1/address-book/{created.json()['id']}",
            **auth_headers(ctx["owner_token"]),
        )
        assert removed.status_code == 200

    def test_viewer_cannot_manage(self, client: Client, ctx):
        assert self._add(client, ctx, ctx["viewer_token"]).status_code == 403
        policy = post(client, "/api/v1/address-book/policy", ctx["viewer_token"], {
            "project_id": str(ctx["project"].id), "required": True}, method="patch")
        assert policy.status_code == 403

    def test_allowlist_enforcement(self, client: Client, ctx):
        # Policy off (default): any destination is accepted.
        self._withdraw(ctx, OTHER, "ab-off")
        policy = post(client, "/api/v1/address-book/policy", ctx["owner_token"], {
            "project_id": str(ctx["project"].id), "required": True}, method="patch")
        assert policy.status_code == 200
        assert policy.json()["withdrawal_allowlist_required"] is True
        # The API toggled the flag on the DB row; drop the fixture's
        # cached project relation (a real request loads it fresh).
        ctx["wallet"].refresh_from_db()
        with pytest.raises(ops_services.OperationsError, match="allowlist"):
            self._withdraw(ctx, OTHER, "ab-on-blocked")
        self._add(client, ctx, ctx["owner_token"], DEST)
        allowed = self._withdraw(ctx, DEST, "ab-on-allowed")
        assert allowed.destination_address == DEST


@pytest.mark.django_db
class TestWebhookSecretRotation:
    def test_rotation_replaces_secret(self, client: Client, ctx):
        endpoint, old_secret = webhook_services.create_endpoint(
            project=ctx["project"], url="https://example.com/hook",
            events=["deposit.credited"], dns_resolver=PUBLIC_DNS,
        )
        forbidden = post(
            client, f"/api/v1/webhooks/endpoints/{endpoint.id}/rotate-secret",
            ctx["viewer_token"], {},
        )
        assert forbidden.status_code == 403
        rotated = post(
            client, f"/api/v1/webhooks/endpoints/{endpoint.id}/rotate-secret",
            ctx["owner_token"], {},
        )
        assert rotated.status_code == 200, rotated.content
        new_secret = rotated.json()["signing_secret"]
        assert new_secret.startswith("whsec_") and new_secret != old_secret
        endpoint.refresh_from_db()
        assert decrypt_secret(endpoint.signing_secret_ciphertext) == new_secret


@pytest.mark.django_db
class TestAutoSweepRules:
    def _rule(self, ctx, threshold: int, enabled: bool = True) -> AutoSweepRule:
        return AutoSweepRule.objects.create(
            project=ctx["project"], wallet=ctx["wallet"], network=ctx["network"],
            asset=ctx["asset"], threshold_amount=threshold, enabled=enabled,
            created_by=ctx["owner"],
        )

    def test_threshold_and_open_sweep_gating(self, ctx):
        below = self._rule(ctx, 2_000_000)
        assert sweep_services.evaluate_auto_sweep_rule(below) is None
        below.delete()  # one rule per (wallet, network, asset)
        rule = self._rule(ctx, 500_000)
        sweep = sweep_services.evaluate_auto_sweep_rule(rule)
        assert sweep is not None
        assert sweep.external_reference == f"auto-sweep:{rule.id}"
        assert sweep.status == Sweep.Status.CREATED
        # An open auto sweep blocks further triggers.
        assert sweep_services.evaluate_auto_sweep_rule(rule) is None
        rule.refresh_from_db()
        assert rule.trigger_count == 1

    def test_disabled_rule_never_triggers(self, ctx):
        rule = self._rule(ctx, 1, enabled=False)
        assert sweep_services.evaluate_auto_sweep_rule(rule) is None

    def test_rule_api(self, client: Client, ctx):
        created = post(client, "/api/v1/auto-sweep-rules", ctx["owner_token"], {
            "wallet_id": str(ctx["wallet"].id), "network": "ethereum",
            "asset_id": str(ctx["asset"].id), "threshold_amount": "500000",
        })
        assert created.status_code == 201, created.content
        assert created.json()["threshold_amount"] == "500000"
        duplicate = post(client, "/api/v1/auto-sweep-rules", ctx["owner_token"], {
            "wallet_id": str(ctx["wallet"].id), "network": "ethereum",
            "asset_id": str(ctx["asset"].id), "threshold_amount": "1",
        })
        assert duplicate.status_code == 409
        forbidden = post(client, "/api/v1/auto-sweep-rules", ctx["viewer_token"], {
            "wallet_id": str(ctx["wallet"].id), "network": "ethereum",
            "asset_id": str(ctx["asset"].id), "threshold_amount": "1",
        })
        assert forbidden.status_code == 403
        call_command("run_auto_sweeps")  # smoke: runs clean, creates the sweep
        assert Sweep.objects.filter(
            external_reference=f"auto-sweep:{created.json()['id']}"
        ).exists()
