"""Run the chain indexer (Phase 5) — a worker entrypoint, separate
from the web processes. Each pass scans a bounded batch of blocks
per EVM network; `--until-caught-up` repeats passes until the lag
is zero. Scheduling/daemonising is the deployment's job (systemd,
Temporal schedules); this command is the unit of work.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from waas.modules.evm.chains import resolve_chain
from waas.modules.evm.provider import EvmProvider
from waas.modules.indexing import services
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.tron.chains import TRON_NETWORK_SLUGS
from waas.modules.tron.chains import resolve_chain as resolve_tron_chain
from waas.modules.tron.indexing import scan_tron_once
from waas.modules.tron.provider import TronProvider

EVM_SLUGS = ["ethereum", "ethereum-sepolia", "bsc", "bsc-testnet"]


class Command(BaseCommand):
    help = "Run EVM indexing passes (deposit detection, confirmations, reorgs)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--network", default="", help="Network slug (default: all EVM).")
        parser.add_argument("--max-blocks", type=int, default=64)
        parser.add_argument(
            "--until-caught-up",
            action="store_true",
            help="Repeat passes until every network's lag is zero.",
        )

    def handle(self, *args, **options) -> None:
        if options["network"]:
            networks = list(BlockchainNetwork.objects.filter(slug=options["network"]))
            if not networks:
                raise CommandError(f"unknown network slug: {options['network']}")
        else:
            networks = list(
                BlockchainNetwork.objects.filter(
                    slug__in=EVM_SLUGS + sorted(TRON_NETWORK_SLUGS)
                )
            )
        while True:
            all_caught_up = True
            for network in networks:
                if network.slug in TRON_NETWORK_SLUGS:
                    provider = TronProvider(resolve_tron_chain(network))
                    report = scan_tron_once(
                        network=network, provider=provider,
                        max_blocks=options["max_blocks"],
                    )
                else:
                    provider = EvmProvider(resolve_chain(network))
                    report = services.scan_once(
                        network=network, provider=provider, max_blocks=options["max_blocks"]
                    )
                self.stdout.write(
                    f"{report.network}: head={report.head} "
                    f"scanned={report.scanned_from}..{report.scanned_to} "
                    f"detected={report.deposits_detected} "
                    f"credited={report.deposits_credited} "
                    f"reorg_depth={report.reorg_depth} lag={report.lag}"
                )
                if report.lag > 0:
                    all_caught_up = False
            if not options["until_caught_up"] or all_caught_up:
                return
