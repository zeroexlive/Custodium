"""Provision one wallet through the MPC signer service.

Operator entrypoint for `waas.modules.wallets.provisioning` — the
same flow the dashboard endpoint runs. Requires the signer gate
(MPC_SIGNER_ENABLED + MPC_SIGNER_URL); with the gate closed this
fails cleanly and the wallet remains `provisioning`.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from waas.modules.wallets.models import Wallet
from waas.modules.wallets.provisioning import (
    ProvisioningUnavailable,
    provision_wallet,
)


class Command(BaseCommand):
    help = "Provision a wallet (MPC key generation + address derivation + activation)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("wallet_id", help="UUID of the wallet to provision")

    def handle(self, *args, **options) -> None:
        wallet = Wallet.objects.filter(id=options["wallet_id"]).first()
        if wallet is None:
            raise CommandError(f"wallet {options['wallet_id']} not found")
        try:
            wallet = provision_wallet(wallet)
        except ProvisioningUnavailable as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"wallet {wallet.id} is now {wallet.status} "
            f"(ecdsa={wallet.ecdsa_key_ref}, ed25519={wallet.ed25519_key_ref})"
        )
        for address in wallet.addresses.select_related("network").order_by(
            "network__slug"
        ):
            self.stdout.write(f"  {address.network.slug:<18} {address.address}")
