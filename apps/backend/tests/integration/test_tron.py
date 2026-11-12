"""Phase 6 TRON: withdrawal pipeline, deposit indexing, reorg —
against an in-memory TronGrid-style double. The signer is the
Phase 4 TEST-ONLY single-key double pattern; production signing
stays fail-closed.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from django.contrib.auth import get_user_model
from django.core.management import call_command

from waas.modules.assets.models import Asset
from waas.modules.blacklist.models import BlacklistEntry
from waas.modules.evm.signing import UnavailableSigner
from waas.modules.indexing.models import ObservedDeposit
from waas.modules.indexing.services import reconciliation_report
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Organization
from waas.modules.projects.models import Project
from waas.modules.tron import addresses, service
from waas.modules.tron import indexing as tron_indexing
from waas.modules.tron.chains import TronChain
from waas.modules.tron.models import TronTransaction
from waas.modules.tron.provider import BroadcastRejected, ProviderUnavailable
from waas.modules.wallets.models import Wallet

pytestmark = pytest.mark.django_db

TEST_KEY = ec.derive_private_key(
    int.from_bytes(bytes.fromhex("46" * 32), "big"), ec.SECP256K1()
)
SENDER_HEX = "41" + "33" * 20
DEST_B58 = addresses.hex_to_base58("41" + "22" * 20)
BLOCK0_ID = "00" * 8 + "1122334455667788" + "00" * 16


class TestSigner:
    """TEST-ONLY signer double (single key). Never production."""

    def wallet_public_key(self, wallet) -> bytes:
        numbers = TEST_KEY.public_key().public_numbers()
        return numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")

    def sign_digest(self, wallet, digest: bytes) -> tuple[int, int]:
        der = TEST_KEY.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return utils.decode_dss_signature(der)


class FakeTronProvider:
    """In-memory TronGrid double with fork support."""

    def __init__(self, network, *, broadcast_mode: str = "ok") -> None:
        self.chain = TronChain(network=network, endpoints=("memory://",))
        self.broadcast_mode = broadcast_mode
        self.head = 0
        self.blocks: dict[int, dict] = {}
        self.infos: dict[str, dict] = {}
        self.broadcasted: list[dict] = []
        self.salt = "a"

    # chain construction -------------------------------------------
    def _block_id(self, number: int) -> str:
        from waas.modules.evm import keys

        return keys.keccak256(f"{self.salt}:{number}".encode()).hex()

    def add_block(self, *, txs=(), timestamp_ms: int = 1_700_000_000_000) -> int:
        number = self.head
        block = {
            "blockID": self._block_id(number),
            "block_header": {
                "raw_data": {
                    "number": number,
                    "parentHash": self._block_id(number - 1) if number else "00" * 32,
                    "timestamp": timestamp_ms,
                }
            },
            "transactions": list(txs),
        }
        self.blocks[number] = block
        self.head = number + 1
        return number

    def transfer_tx(self, *, to_hex: str, amount: int, txid: str, success: bool = True) -> dict:
        return {
            "txID": txid,
            "ret": [{"contractRet": "SUCCESS" if success else "REVERT"}],
            "raw_data": {
                "contract": [
                    {
                        "type": "TransferContract",
                        "parameter": {
                            "value": {
                                "owner_address": SENDER_HEX,
                                "to_address": to_hex,
                                "amount": amount,
                            }
                        },
                    }
                ]
            },
        }

    def reorg(self, from_number: int) -> None:
        self.salt = "b"
        for number in range(from_number, self.head):
            self.blocks[number] = {
                "blockID": self._block_id(number),
                "block_header": {"raw_data": {"number": number, "parentHash": "00" * 32, "timestamp": 1}},
                "transactions": [],
            }

    # provider surface ----------------------------------------------
    def now_block(self) -> dict:
        number = max(self.head - 1, 0)
        return {
            "number": number,
            "block_id": self.blocks[number]["blockID"] if self.blocks else BLOCK0_ID,
            "timestamp_ms": 1_700_000_000_000,
        }

    def head_number(self) -> int:
        return max(self.head - 1, 0)

    def get_block(self, number: int) -> dict | None:
        return self.blocks.get(number)

    def get_block_id(self, number: int) -> str | None:
        block = self.blocks.get(number)
        return None if block is None else block["blockID"]

    def get_account(self, address_hex: str) -> dict:
        return {"address": address_hex, "balance": 0}

    def get_transaction_info(self, tx_id: str) -> dict | None:
        return self.infos.get(tx_id)

    def broadcast(self, tx_json: dict) -> str:
        if self.broadcast_mode == "reject":
            raise BroadcastRejected("SIGERROR: invalid signature")
        if self.broadcast_mode == "down":
            raise ProviderUnavailable("node unreachable")
        self.broadcasted.append(tx_json)
        return tx_json["txID"]


@pytest.fixture()
def ctx():
    call_command("seed_networks_assets")
    user = get_user_model().objects.create_user(email="tron@example.com", password="x" * 12)
    org = Organization.objects.create(name="Tron Org", slug="tron-org")
    project = Project.objects.create(
        organization=org, name="Main", environment="sandbox", created_by=user
    )
    tron = BlockchainNetwork.objects.get(slug="tron")
    tron.confirmations_required = 2
    tron.save(update_fields=["confirmations_required"])
    wallet = Wallet.objects.create(project=project, label="ops", external_customer_id="cust_1")
    signer = TestSigner()
    service.register_wallet_tron_addresses(
        wallet=wallet, ecdsa_public_key=signer.wallet_public_key(wallet)
    )
    return {
        "project": project,
        "wallet": wallet,
        "tron": tron,
        "trx": Asset.objects.get(network=tron, symbol="TRX"),
        "usdt": Asset.objects.get(network=tron, symbol="USDT"),
        "user": user,
        "owner_hex": addresses.hex_from_public_key(signer.wallet_public_key(wallet)),
    }


def credit(ctx, asset, amount: int) -> None:
    from waas.modules.ledger.models import JournalEntry

    scope = "cust_1"
    ledger_services.post_journal(
        project=ctx["project"],
        asset=asset,
        entry_type=JournalEntry.EntryType.DEPOSIT_CREDIT,
        lines=[
            {"account": ledger_services.get_or_create_account(
                project=ctx["project"], asset=asset, account_type=AccountType.CUSTODY_ONCHAIN),
             "side": "debit", "amount": amount},
            {"account": ledger_services.get_or_create_account(
                project=ctx["project"], asset=asset,
                account_type=AccountType.CUSTOMER_AVAILABLE, external_ref=scope),
             "side": "credit", "amount": amount},
        ],
        idempotency_key=f"seed:{asset.id}",
        operation_type="deposit",
        operation_id="seed",
    )


def balance(ctx, asset, account_type, ref="cust_1") -> int:
    account = ledger_services.get_or_create_account(
        project=ctx["project"], asset=asset, account_type=account_type, external_ref=ref
    )
    return ledger_services.account_balance(account)


def withdraw(ctx, provider, **overrides):
    params = {
        "wallet": ctx["wallet"],
        "network": ctx["tron"],
        "asset": ctx["trx"],
        "to_address": DEST_B58,
        "amount": 2_000_000,
        "idempotency_key": "wd-tron-1",
        "signer": TestSigner(),
        "provider": provider,
    }
    params.update(overrides)
    return service.execute_withdrawal(**params)


# ---------------------------------------------------------- withdrawals


def test_trx_withdrawal_round_trip(ctx) -> None:
    credit(ctx, ctx["trx"], 5_000_000)
    provider = FakeTronProvider(ctx["tron"])
    provider.add_block()
    tx = withdraw(ctx, provider)
    assert tx.status == TronTransaction.Status.BROADCAST
    assert len(provider.broadcasted) == 1
    assert provider.broadcasted[0]["txID"] == tx.tx_id
    assert len(bytes.fromhex(tx.signature_hex)) == 65
    # Signature recovers to the wallet's own TRON address.
    from waas.modules.evm import keys as evm_keys

    sig = bytes.fromhex(tx.signature_hex)
    r, s, v = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:64], "big"), sig[64]
    recovered = evm_keys.recover_public_key(bytes.fromhex(tx.tx_id), r, s, v)
    assert addresses.hex_from_public_key(recovered) == ctx["owner_hex"]

    provider.infos[tx.tx_id] = {
        "id": tx.tx_id, "blockNumber": 1, "fee": 0, "receipt": {"result": "SUCCESS"},
    }
    provider.add_block()
    provider.add_block()  # head 2 -> 2 confirmations for block 1
    tx = service.confirm_transaction(tx=tx, provider=provider)
    assert tx.status == TronTransaction.Status.CONFIRMED
    assert balance(ctx, ctx["trx"], AccountType.CUSTOMER_AVAILABLE) == 3_000_000
    assert balance(ctx, ctx["trx"], AccountType.WITHDRAWAL_RESERVED) == 0
    assert balance(ctx, ctx["trx"], AccountType.CUSTODY_ONCHAIN, ref="") == 3_000_000
    assert ledger_services.trial_balance(ctx["project"], ctx["trx"]) == 0


def test_usdt_withdrawal_builds_trigger_contract(ctx) -> None:
    credit(ctx, ctx["usdt"], 1_000_000)
    provider = FakeTronProvider(ctx["tron"])
    provider.add_block()
    tx = withdraw(
        ctx, provider, asset=ctx["usdt"], amount=250_000, idempotency_key="wd-usdt-1"
    )
    assert tx.status == TronTransaction.Status.BROADCAST
    assert tx.contract_type == "TriggerSmartContract"
    assert tx.fee_limit_sun == 15_000_000
    sent = provider.broadcasted[0]
    assert sent["raw_data"]["contract"][0]["type"] == "TriggerSmartContract"


def test_signer_unavailable_aborts_and_releases(ctx) -> None:
    credit(ctx, ctx["trx"], 5_000_000)
    provider = FakeTronProvider(ctx["tron"])
    provider.add_block()
    tx = withdraw(ctx, provider, signer=UnavailableSigner())
    assert tx.status == TronTransaction.Status.FAILED
    assert provider.broadcasted == []
    assert balance(ctx, ctx["trx"], AccountType.CUSTOMER_AVAILABLE) == 5_000_000
    assert balance(ctx, ctx["trx"], AccountType.WITHDRAWAL_RESERVED) == 0


def test_broadcast_unknown_outcome_holds_reservation(ctx) -> None:
    credit(ctx, ctx["trx"], 5_000_000)
    provider = FakeTronProvider(ctx["tron"], broadcast_mode="down")
    provider.add_block()
    tx = withdraw(ctx, provider)
    assert tx.status == TronTransaction.Status.DROPPED
    assert balance(ctx, ctx["trx"], AccountType.WITHDRAWAL_RESERVED) == 2_000_000


def test_blacklisted_destination_refused(ctx) -> None:
    BlacklistEntry.objects.create(
        scope="platform", network=ctx["tron"], address=DEST_B58,
        normalized_address=addresses.normalize_to_hex(DEST_B58),
        reason="test", created_by=ctx["user"],
    )
    provider = FakeTronProvider(ctx["tron"])
    provider.add_block()
    with pytest.raises(service.TronServiceError):
        withdraw(ctx, provider)
    assert TronTransaction.objects.count() == 0


# ------------------------------------------------------------ deposits


def test_trx_deposit_indexing_and_credit(ctx) -> None:
    provider = FakeTronProvider(ctx["tron"])
    provider.add_block(
        txs=[provider.transfer_tx(to_hex=ctx["owner_hex"], amount=7_000_000, txid="ab" * 32)]
    )
    provider.add_block()  # 2 confirmations (required = 2)
    report = tron_indexing.scan_tron_once(network=ctx["tron"], provider=provider)
    assert report.deposits_detected == 1
    deposit = ObservedDeposit.objects.get()
    assert deposit.asset == ctx["trx"]
    assert deposit.status == ObservedDeposit.Status.CREDITED
    assert balance(ctx, ctx["trx"], AccountType.CUSTOMER_AVAILABLE) == 7_000_000
    # Replay: no double credit.
    report = tron_indexing.scan_tron_once(network=ctx["tron"], provider=provider)
    assert ObservedDeposit.objects.count() == 1
    assert balance(ctx, ctx["trx"], AccountType.CUSTOMER_AVAILABLE) == 7_000_000


def test_trc20_deposit_indexing(ctx) -> None:
    from waas.modules.indexing.services import TRANSFER_TOPIC

    provider = FakeTronProvider(ctx["tron"])
    txid = "cd" * 32
    trigger = {
        "txID": txid,
        "ret": [{"contractRet": "SUCCESS"}],
        "raw_data": {
            "contract": [
                {
                    "type": "TriggerSmartContract",
                    "parameter": {
                        "value": {
                            "owner_address": SENDER_HEX,
                            "contract_address": addresses.normalize_to_hex(
                                ctx["usdt"].contract_or_mint_address
                            ),
                            "data": "",
                        }
                    },
                }
            ]
        },
    }
    provider.add_block(txs=[trigger])
    provider.add_block()
    usdt_body = addresses.normalize_to_hex(ctx["usdt"].contract_or_mint_address)[2:]
    provider.infos[txid] = {
        "id": txid,
        "blockNumber": 0,
        "receipt": {"result": "SUCCESS"},
        "log": [
            {
                "address": usdt_body,
                "topics": [
                    TRANSFER_TOPIC[2:],
                    "00" * 12 + SENDER_HEX[2:],
                    "00" * 12 + ctx["owner_hex"][2:],
                ],
                "data": hex(400_000_000)[2:].rjust(64, "0"),
            }
        ],
    }
    tron_indexing.scan_tron_once(network=ctx["tron"], provider=provider)
    deposit = ObservedDeposit.objects.get()
    assert deposit.asset == ctx["usdt"]
    assert int(deposit.amount) == 400_000_000
    assert deposit.status == ObservedDeposit.Status.CREDITED
    assert balance(ctx, ctx["usdt"], AccountType.CUSTOMER_AVAILABLE) == 400_000_000


def test_tron_reorg_reverses_deposit(ctx) -> None:
    provider = FakeTronProvider(ctx["tron"])
    provider.add_block(
        txs=[provider.transfer_tx(to_hex=ctx["owner_hex"], amount=7_000_000, txid="ab" * 32)]
    )
    provider.add_block()
    tron_indexing.scan_tron_once(network=ctx["tron"], provider=provider)
    assert balance(ctx, ctx["trx"], AccountType.CUSTOMER_AVAILABLE) == 7_000_000
    provider.reorg(0)
    tron_indexing.scan_tron_once(network=ctx["tron"], provider=provider)
    deposit = ObservedDeposit.objects.get()
    assert deposit.status == ObservedDeposit.Status.REORGED_OUT
    assert balance(ctx, ctx["trx"], AccountType.CUSTOMER_AVAILABLE) == 0
    assert ledger_services.trial_balance(ctx["project"], ctx["trx"]) == 0
    report = reconciliation_report(network=ctx["tron"])
    assert next(r for r in report["assets"] if r["asset"] == "TRX")["balanced"] is True
