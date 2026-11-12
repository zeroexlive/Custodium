"""Run the Phase 5 reconciliation report for every network and
raise/clear fail-closed withdrawal halts from the results
(Phase 9 discrepancy halt)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from waas.modules.indexing.services import reconciliation_report
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.operations import services


class Command(BaseCommand):
    help = "Reconcile all networks and update withdrawal halts."

    def handle(self, *args, **options) -> None:
        for network in BlockchainNetwork.objects.all():
            report = reconciliation_report(network=network)
            halted = services.apply_reconciliation_report(network=network, report=report)
            state = "HALTED" if halted else "ok"
            self.stdout.write(f"{network.slug}: {state}")
