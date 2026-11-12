"""Worker entrypoint for the withdrawal lifecycle: dispatch
approved requests and refresh in-flight ones. Designed to be run
repeatedly (cron/Temporal in production); every step is
idempotent.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from waas.modules.operations import services
from waas.modules.operations.models import WithdrawalRequest


class Command(BaseCommand):
    help = "Dispatch approved withdrawals and refresh in-flight ones."

    def handle(self, *args, **options) -> None:
        dispatched = 0
        for request in WithdrawalRequest.objects.filter(
            status=WithdrawalRequest.Status.APPROVED
        ):
            services.dispatch_withdrawal(request=request)
            dispatched += 1
        refreshed = 0
        for request in WithdrawalRequest.objects.filter(
            status__in=[
                WithdrawalRequest.Status.BROADCAST,
                WithdrawalRequest.Status.CONFIRMING,
            ]
        ):
            before = request.status
            services.refresh_withdrawal(request=request)
            if request.status != before:
                refreshed += 1
        self.stdout.write(
            f"dispatched={dispatched} transitions={refreshed}"
        )
