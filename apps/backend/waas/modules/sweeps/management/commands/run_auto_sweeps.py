"""Evaluate auto-sweep rules and create any triggered sweeps.

Run on the worker cadence (e.g. every minute) alongside
`process_sweeps`. Creation goes through the ordinary sweep path;
this command only decides WHEN a sweep comes into existence.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from waas.modules.sweeps import services
from waas.modules.sweeps.models import AutoSweepRule


class Command(BaseCommand):
    help = "Create sweeps for auto-sweep rules whose balance threshold is met."

    def handle(self, *args, **options) -> None:
        created = 0
        rules = AutoSweepRule.objects.filter(enabled=True).select_related(
            "wallet", "network", "asset", "project"
        )
        for rule in rules:
            try:
                sweep = services.evaluate_auto_sweep_rule(rule)
            except services.SweepError as exc:
                self.stderr.write(f"rule {rule.id}: {exc}")
                continue
            if sweep is not None:
                created += 1
                self.stdout.write(f"rule {rule.id}: created sweep {sweep.id}")
        self.stdout.write(f"auto-sweeps: {created} sweep(s) created")
