"""Worker entrypoint for sweeps: resolve + execute pending
sweeps and refresh in-flight ones. Every step is persisted, so a
crash resumes from the last state (sweep-resolver.md §4).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from waas.modules.sweeps import services
from waas.modules.sweeps.models import Sweep


class Command(BaseCommand):
    help = "Process pending sweeps and refresh in-flight ones."

    def handle(self, *args, **options) -> None:
        processed = 0
        for sweep in Sweep.objects.filter(
            status__in=[Sweep.Status.CREATED, Sweep.Status.RESOLVED]
        ):
            services.process_sweep(sweep=sweep)
            processed += 1
        refreshed = 0
        for sweep in Sweep.objects.filter(
            status__in=[Sweep.Status.BROADCAST, Sweep.Status.CONFIRMING]
        ):
            before = sweep.status
            services.refresh_sweep(sweep=sweep)
            if sweep.status != before:
                refreshed += 1
        self.stdout.write(f"processed={processed} transitions={refreshed}")
