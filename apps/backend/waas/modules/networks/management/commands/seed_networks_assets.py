"""Seed the network + asset registry with verified identities.

Sources verified 2026-11-12 (see docs/blockchains/capability-matrix.md):
- USDT identity is chain-specific and NEVER keyed by symbol alone.
- BSC USDT is Binance-Peg (bridged_pegged), NOT issuer-native Tether.
Deposits/withdrawals stay DISABLED for every asset until the indexing (Phase 5)
and MPC signing (Phase 3) subsystems exist and are reviewed.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from waas.modules.assets.models import Asset
from waas.modules.networks.models import BlockchainNetwork

NETWORKS = [
    # slug, name, chain_id, native, native_decimals, family, testnet, confirmations, finality
    ("ethereum", "Ethereum", 1, "ETH", 18, "ecdsa_secp256k1", False, 12,
     "Probabilistic; consider ~2 epochs for economic finality"),
    ("ethereum-sepolia", "Ethereum Sepolia (testnet)", 11155111, "ETH", 18, "ecdsa_secp256k1", True, 12, "Testnet"),
    ("bsc", "BNB Smart Chain", 56, "BNB", 18, "ecdsa_secp256k1", False, 15, "Fast finality (BEP-126) where supported"),
    ("bsc-testnet", "BNB Smart Chain Testnet", 97, "BNB", 18, "ecdsa_secp256k1", True, 15, "Testnet"),
    ("tron", "TRON", None, "TRX", 6, "ecdsa_secp256k1", False, 19, "Solidified blocks (~19 blocks)"),
    ("tron-nile", "TRON Nile (testnet)", None, "TRX", 6, "ecdsa_secp256k1", True, 19, "Testnet"),
    ("solana", "Solana", None, "SOL", 9, "ed25519", False, 32, "Finalized commitment (~32 slots)"),
    ("solana-devnet", "Solana Devnet", None, "SOL", 9, "ed25519", True, 32, "Testnet"),
    ("ton", "TON", None, "TON", 9, "ed25519", False, 0, "Shardchain finality via masterchain"),
    ("ton-testnet", "TON Testnet", None, "TON", 9, "ed25519", True, 0, "Testnet"),
]

# network_slug, symbol, name, decimals, standard, contract/mint/master, program,
# issuer_classification, verification_status
ASSETS = [
    ("ethereum", "ETH", "Ether", 18, "native", None, "", "native", "verified"),
    ("ethereum-sepolia", "ETH", "Ether (Sepolia)", 18, "native", None, "", "native", "verified"),
    ("bsc", "BNB", "BNB", 18, "native", None, "", "native", "verified"),
    ("bsc-testnet", "BNB", "BNB (testnet)", 18, "native", None, "", "native", "verified"),
    ("tron", "TRX", "TRON", 6, "native", None, "", "native", "verified"),
    ("tron-nile", "TRX", "TRON (Nile)", 6, "native", None, "", "native", "verified"),
    ("solana", "SOL", "Solana", 9, "native", None, "", "native", "verified"),
    ("solana-devnet", "SOL", "Solana (devnet)", 9, "native", None, "", "native", "verified"),
    ("ton", "TON", "Toncoin", 9, "native", None, "", "native", "verified"),
    ("ton-testnet", "TON", "Toncoin (testnet)", 9, "native", None, "", "native", "verified"),
    # USDT — verified issuer identities (decimals/classification differ per chain!)
    ("ethereum", "USDT", "Tether USD₮", 6, "ERC-20",
     "0xdAC17F958D2ee523a2206206994597C13D831ec7", "", "issuer_native", "verified"),
    ("bsc", "USDT", "Binance-Peg USD₮", 18, "BEP-20",
     "0x55d398326f99059fF775485246999027B3197955", "", "bridged_pegged", "verified"),
    ("tron", "USDT", "Tether USD₮", 6, "TRC-20",
     "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "", "issuer_native", "verified"),
    ("solana", "USDT", "Tether USD₮", 6, "SPL",
     "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
     "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "issuer_native", "verified"),
    ("ton", "USDT", "Tether USD₮", 6, "Jetton",
     "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs", "", "issuer_native", "verified"),
]


class Command(BaseCommand):
    help = "Seed blockchain networks and verified native/USDT assets (idempotent)."

    def handle(self, *args: object, **options: object) -> None:
        networks: dict[str, BlockchainNetwork] = {}
        for slug, name, chain_id, native, decimals, family, testnet, confs, finality in NETWORKS:
            network, _ = BlockchainNetwork.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name, "chain_id": chain_id, "native_symbol": native,
                    "native_decimals": decimals, "signature_family": family,
                    "is_testnet": testnet,
                    "operational_status": BlockchainNetwork.OperationalStatus.PLANNED,
                    "confirmations_required": confs, "finality_description": finality,
                },
            )
            networks[slug] = network
        created = 0
        for (slug, symbol, name, decimals, standard, contract, program,
             classification, verification) in ASSETS:
            _, was_created = Asset.objects.update_or_create(
                network=networks[slug], token_standard=standard, contract_or_mint_address=contract,
                defaults={
                    "symbol": symbol, "name": name, "decimals": decimals,
                    "token_program": program, "issuer_classification": classification,
                    "verification_status": verification,
                    "deposit_enabled": False, "withdrawal_enabled": False,
                    "operational_status": Asset.OperationalStatus.PLANNED,
                },
            )
            created += int(was_created)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(networks)} networks, {len(ASSETS)} assets ({created} new). "
                "Deposits/withdrawals remain disabled."
            )
        )
