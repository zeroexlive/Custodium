"""Phase 11 webhooks: signed delivery, retry ladder, dead
letters, replay, and emission from a real withdrawal completion.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_module
import json

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from django.contrib.auth import get_user_model
from django.core.management import call_command

from waas.modules.assets.models import Asset
from waas.modules.evm import keys as evm_keys
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.operations import dispatch
from waas.modules.operations import services as op_services
from waas.modules.operations.models import WithdrawalPolicy
from waas.modules.organizations.models import Membership, Organization
from waas.modules.projects.models import Project
from waas.modules.wallets import services as wallet_services
from waas.modules.wallets.models import Wallet
from waas.modules.webhooks import services
from waas.modules.webhooks.models import WebhookDelivery, WebhookEvent

pytestmark = pytest.mark.django_db

PUBLIC_DNS = lambda host: ["93.184.216.34"]  # noqa: E731
_EC_KEY = ec.derive_private_key(int.from_bytes(b"\x33" * 32, "big"), ec.SECP256K1())
_N = _EC_KEY.public_key().public_numbers()
TEST_PUBKEY = _N.x.to_bytes(32, "big") + _N.y.to_bytes(32, "big")
FROM = evm_keys.address_from_public_key(TEST_PUBKEY)
DEST = "0x3535353535353535353535353535353535353535"


class TestSigner:
    def wallet_public_key(self, wallet) -> bytes:
        return TEST_PUBKEY

    def sign_digest(self, wallet, digest: bytes):
        der = _EC_KEY.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return utils.decode_dss_signature(der)


class FakeProvider:
    def __init__(self, network) -> None:
        from waas.modules.evm.chains import EvmChain

        self.chain = EvmChain(network=network, endpoints=("memory://",))
        self.receipt: dict | None = None

    def verify_chain(self):
        return self.chain.chain_id

    def get_transaction_count(self, address):
        return 0

    def fee_data(self):
        return (3_000_000_000, 1_000_000_000)

    def estimate_gas(self, **kwargs):
        return 50_000

    def send_raw_transaction(self, raw):
        return "0x" + (b"\xef" * 32).hex()

    def get_receipt(self, tx_hash):
        return self.receipt

    def block_number(self):
        return 2000


def factories(provider):
    return dispatch.Factories(
        provider=lambda network: provider,
        ecdsa_signer=lambda: TestSigner(),
        ed25519_signer=lambda: TestSigner(),
    )


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    User = get_user_model()
    org = Organization.objects.create(name="Hook Org", slug="hook-org")
    owner = User.objects.create_user(email="hook-owner@example.com", password="x" * 12)
    Membership.objects.create(organization=org, user=owner, role=Membership.Role.OWNER)
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=owner
    )
    network = BlockchainNetwork.objects.get(slug="ethereum")
    network.confirmations_required = 1
    network.save(update_fields=["confirmations_required"])
    asset = Asset.objects.get(network=network, symbol="USDT")
    wallet = Wallet.objects.create(project=project, label="ops", external_customer_id="cust_1")
    wallet_services.record_derived_address(
        wallet=wallet, network=network, address=FROM, derivation_path="custodium/evm/1"
    )
    wallet.refresh_from_db()
    ledger_services.post_journal(
        project=project, asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset, account_type=AccountType.CUSTODY_ONCHAIN),
             "side": "debit", "amount": 500_000},
            {"account": ledger_services.get_or_create_account(
                project=project, asset=asset,
                account_type=AccountType.CUSTOMER_AVAILABLE, external_ref="cust_1"),
             "side": "credit", "amount": 500_000},
        ],
        idempotency_key="seed:hooks", operation_type="deposit", operation_id="seed",
    )
    return {"org": org, "project": project, "network": network, "asset": asset,
            "wallet": wallet, "owner": owner}


def capturing_client(captured: list, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_signed_delivery_and_headers(ctx) -> None:
    endpoint, secret = services.create_endpoint(
        project=ctx["project"], url="https://tenant.example/hooks",
        events=["withdrawal.completed"], dns_resolver=PUBLIC_DNS,
    )
    assert secret.startswith("whsec_")
    assert secret not in endpoint.signing_secret_ciphertext  # stored encrypted
    event = services.emit_event(
        project=ctx["project"], event_type="withdrawal.completed",
        data={"withdrawal_id": "abc", "amount": "5"},
    )
    assert event is not None
    # Unsubscribed types create nothing.
    assert services.emit_event(
        project=ctx["project"], event_type="sweep.failed", data={}
    ) is None
    delivery = WebhookDelivery.objects.get(event=event)
    captured: list = []
    services.attempt_delivery(
        delivery, http_client=capturing_client(captured), dns_resolver=PUBLIC_DNS
    )
    delivery.refresh_from_db()
    assert delivery.status == WebhookDelivery.Status.DELIVERED
    request = captured[0]
    assert request.headers["x-waas-event-type"] == "withdrawal.completed"
    assert request.headers["x-waas-event-id"] == str(event.id)
    # Signature verifies independently against the documented scheme.
    header = request.headers["waas-signature"]
    timestamp, signature = header.split(",")[0].split("=")[1], header.split("v1=")[1]
    expected = hmac_module.new(
        secret.encode(), f"{timestamp}.".encode() + request.content, hashlib.sha256
    ).hexdigest()
    assert signature == expected
    body = json.loads(request.content)
    assert body["id"] == str(event.id)
    assert body["data"]["amount"] == "5"


def test_retry_ladder_dead_letter_and_replay(ctx) -> None:
    endpoint, _secret = services.create_endpoint(
        project=ctx["project"], url="https://tenant.example/hooks",
        events=["deposit.credited"], dns_resolver=PUBLIC_DNS,
    )
    services.emit_event(
        project=ctx["project"], event_type="deposit.credited", data={"amount": "1"}
    )
    delivery = WebhookDelivery.objects.get()
    failing = capturing_client([], status=500)
    for _ in range(6):
        services.attempt_delivery(delivery, http_client=failing, dns_resolver=PUBLIC_DNS)
        delivery.refresh_from_db()
    assert delivery.status == WebhookDelivery.Status.DEAD
    assert delivery.attempts == 6
    assert delivery.last_status_code == 500
    services.replay_delivery(delivery)
    assert delivery.status == WebhookDelivery.Status.PENDING
    assert delivery.attempts == 0
    # SSRF: an endpoint whose host resolves inward fails closed.
    bad, _ = services.create_endpoint(
        project=ctx["project"], url="https://hooks.internal.example/x",
        events=["deposit.credited"], dns_resolver=PUBLIC_DNS,
    )
    services.emit_event(
        project=ctx["project"], event_type="deposit.credited", data={"amount": "2"}
    )
    bad_delivery = WebhookDelivery.objects.filter(endpoint=bad).get()
    services.attempt_delivery(
        bad_delivery, http_client=capturing_client([]),
        dns_resolver=lambda host: ["192.168.1.10"],
    )
    bad_delivery.refresh_from_db()
    assert bad_delivery.status == WebhookDelivery.Status.PENDING  # scheduled, not delivered
    assert "ssrf" in bad_delivery.last_error


def test_withdrawal_completion_emits_event(ctx) -> None:
    services.create_endpoint(
        project=ctx["project"], url="https://tenant.example/hooks",
        events=["withdrawal.completed"], dns_resolver=PUBLIC_DNS,
    )
    WithdrawalPolicy.objects.create(
        project=ctx["project"], asset=None, approvals_required=0
    )
    request = op_services.create_withdrawal_request(
        wallet=ctx["wallet"], network=ctx["network"], asset=ctx["asset"],
        destination_address=DEST, amount=100_000, idempotency_key="emit-1",
    )
    provider = FakeProvider(ctx["network"])
    op_services.dispatch_withdrawal(request=request, factories=factories(provider))
    provider.receipt = {
        "status": "0x1", "blockNumber": hex(1999),
        "gasUsed": hex(21_000), "effectiveGasPrice": hex(1_000_000_000),
    }
    op_services.refresh_withdrawal(request=request, factories=factories(provider))
    event = WebhookEvent.objects.get(event_type="withdrawal.completed")
    assert event.payload["withdrawal_id"] == str(request.id)
    assert event.payload["amount"] == "100000"
    assert WebhookDelivery.objects.filter(event=event).count() == 1
