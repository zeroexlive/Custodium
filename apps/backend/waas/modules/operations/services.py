"""Phase 9 operations services: policy evaluation, the request
lifecycle, service-fee accounting, reconciliation halts, refunds,
and finance exports.

Safety invariants enforced here (on top of the chain pipelines):

- A reconciliation halt on a network refuses NEW withdrawals
  (fail closed) until a clean reconciliation clears it.
- Policy hard limits (single / daily velocity) reject at
  creation with the reason recorded — never silently queued.
- Maker-checker: a dashboard user who requested a withdrawal can
  never approve it; each approver acts at most once.
- The service fee is charged by journal at dispatch (before any
  chain execution) and reversed if the withdrawal later fails,
  so fee income never survives a failed payout.
"""

from __future__ import annotations

import csv
import io
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from waas.modules.assets.models import Asset
from waas.modules.audit.models import AuditEvent
from waas.modules.blacklist import services as blacklist_services
from waas.modules.gasstation.services import GasTopUpPending
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType, JournalEntry
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.organizations.models import Membership
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet

from . import dispatch
from .models import (
    PlatformHalt,
    ReconciliationHalt,
    WithdrawalApproval,
    WithdrawalPolicy,
    WithdrawalRequest,
)

APPROVER_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.ADMINISTRATOR,
    Membership.Role.WITHDRAWAL_APPROVER,
}
REQUESTER_ROLES = APPROVER_ROLES | {Membership.Role.FINANCE_OPERATOR}


class OperationsError(Exception):
    """A business-rule refusal (policy, halt, state, permission)."""


# ---------------------------------------------------------------- policy


def resolve_policy(*, project: Project, asset: Asset) -> WithdrawalPolicy:
    """Asset-specific policy, else the project default, else an
    unsaved platform default (1 approval, no limits, no fee)."""
    specific = WithdrawalPolicy.objects.filter(project=project, asset=asset).first()
    if specific is not None:
        return specific
    default = WithdrawalPolicy.objects.filter(project=project, asset__isnull=True).first()
    if default is not None:
        return default
    return WithdrawalPolicy(project=project, asset=None, approvals_required=1)


def _daily_total(*, wallet: Wallet, asset: Asset) -> int:
    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        WithdrawalRequest.objects.filter(
            wallet=wallet, asset=asset, created_at__gte=start
        )
        .exclude(
            status__in=[WithdrawalRequest.Status.REJECTED, WithdrawalRequest.Status.FAILED]
        )
        .aggregate(total=Sum("amount"))["total"]
    )
    return int(total or 0)


def _halt_active(network: BlockchainNetwork) -> bool:
    # Queried fresh every time: a cached related object would keep
    # a cleared halt (or miss a newly raised one).
    return ReconciliationHalt.objects.filter(network=network, active=True).exists()


def _assert_not_platform_halted(*, action: str) -> None:
    """Phase 12 kill switch: the global PlatformHalt refuses
    money movement platform-wide while active."""
    if PlatformHalt.is_active():
        raise OperationsError(f"{action} refused: platform halt is active (kill switch)")


# ---------------------------------------------------------------- create


@transaction.atomic
def create_withdrawal_request(
    *,
    wallet: Wallet,
    network: BlockchainNetwork,
    asset: Asset,
    destination_address: str,
    amount: int,
    idempotency_key: str,
    external_reference: str = "",
    requested_by_type: str = "api",
    requested_by_id: str = "",
) -> WithdrawalRequest:
    project = wallet.project
    existing = WithdrawalRequest.objects.filter(
        project=project, idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        return existing
    if asset.network_id != network.id:
        raise OperationsError("asset does not belong to the network")
    if amount <= 0:
        raise OperationsError("amount must be positive")
    _assert_not_platform_halted(action="withdrawal creation")
    if _halt_active(network):
        raise OperationsError(
            f"withdrawals on {network.slug} are halted pending reconciliation"
        )
    if blacklist_services.is_blacklisted(
        address=destination_address, network=network, project=project
    ):
        raise OperationsError("destination address is blacklisted")
    if project.withdrawal_allowlist_required:
        from waas.modules.addressbook import services as addressbook_services

        if not addressbook_services.is_allowlisted(
            project=project, network=network, address=destination_address
        ):
            raise OperationsError(
                "destination address is not on this project's allowlist "
                "(destination address book)"
            )

    policy = resolve_policy(project=project, asset=asset)
    request = WithdrawalRequest(
        project=project,
        wallet=wallet,
        network=network,
        asset=asset,
        destination_address=destination_address,
        amount=amount,
        external_reference=external_reference,
        idempotency_key=idempotency_key,
        requested_by_type=requested_by_type,
        requested_by_id=requested_by_id,
        service_fee=int(policy.service_fee_flat),
    )
    # Hard policy limits reject immediately, with the reason kept.
    if policy.min_single_amount is not None and amount < int(policy.min_single_amount):
        request.status = WithdrawalRequest.Status.REJECTED
        request.status_reason = (
            f"policy: single-withdrawal minimum is {int(policy.min_single_amount)}"
        )
    elif policy.max_single_amount is not None and amount > int(policy.max_single_amount):
        request.status = WithdrawalRequest.Status.REJECTED
        request.status_reason = (
            f"policy: single-withdrawal limit is {int(policy.max_single_amount)}"
        )
    elif policy.daily_limit is not None and (
        _daily_total(wallet=wallet, asset=asset) + amount > int(policy.daily_limit)
    ):
        request.status = WithdrawalRequest.Status.REJECTED
        request.status_reason = "policy: daily velocity limit would be exceeded"
    else:
        required = (
            0
            if amount <= int(policy.auto_approve_below)
            else int(policy.approvals_required)
        )
        request.approvals_required = required
        request.status = (
            WithdrawalRequest.Status.APPROVED
            if required == 0
            else WithdrawalRequest.Status.PENDING_POLICY
        )
    request.save()
    AuditEvent.record(
        "withdrawal.created",
        actor_user=None,
        organization=project.organization,
        project=project,
        metadata={
            "request": str(request.id),
            "status": request.status,
            "amount": str(amount),
            "asset": asset.symbol,
            "network": network.slug,
            "actor": f"{requested_by_type}:{requested_by_id}",
        },
    )
    return request


# --------------------------------------------------------------- approvals


@transaction.atomic
def record_approval(
    *, request: WithdrawalRequest, approver, decision: str, note: str = ""
) -> WithdrawalRequest:
    if request.status != WithdrawalRequest.Status.PENDING_POLICY:
        raise OperationsError(f"request is {request.status}, not pending policy")
    membership = Membership.objects.filter(
        organization=request.project.organization, user=approver
    ).first()
    if membership is None or membership.role not in APPROVER_ROLES:
        raise OperationsError("approver lacks a withdrawal approval role")
    if (
        request.requested_by_type == "dashboard"
        and request.requested_by_id == str(approver.id)
    ):
        raise OperationsError("maker-checker: the requester cannot approve their own withdrawal")
    if WithdrawalApproval.objects.filter(request=request, approver=approver).exists():
        raise OperationsError("this approver has already decided on this request")
    WithdrawalApproval.objects.create(
        request=request, approver=approver, decision=decision, note=note
    )
    if decision == WithdrawalApproval.Decision.REJECTED:
        request.status = WithdrawalRequest.Status.REJECTED
        request.status_reason = f"rejected by approver {approver.id}"
    else:
        approvals = WithdrawalApproval.objects.filter(
            request=request, decision=WithdrawalApproval.Decision.APPROVED
        ).count()
        if approvals >= request.approvals_required:
            request.status = WithdrawalRequest.Status.APPROVED
    request.save(update_fields=["status", "status_reason", "updated_at"])
    AuditEvent.record(
        f"withdrawal.{decision}",
        actor_user=approver,
        organization=request.project.organization,
        project=request.project,
        metadata={"request": str(request.id), "status": request.status},
    )
    return request


# ------------------------------------------------------------ fee handling


def _charge_service_fee(request: WithdrawalRequest) -> None:
    fee = int(request.service_fee)
    if fee <= 0 or request.service_fee_charged:
        return
    scope = request.wallet.external_customer_id or f"wallet:{request.wallet.id}"
    ledger_services.post_journal(
        project=request.project,
        asset=request.asset,
        entry_type=JournalEntry.EntryType.FEE,
        lines=[
            {
                "account": ledger_services.get_or_create_account(
                    project=request.project,
                    asset=request.asset,
                    account_type=AccountType.CUSTOMER_AVAILABLE,
                    external_ref=scope,
                ),
                "side": "debit",
                "amount": fee,
            },
            {
                "account": ledger_services.get_or_create_account(
                    project=request.project,
                    asset=request.asset,
                    account_type=AccountType.PLATFORM_FEES_PAYABLE,
                ),
                "side": "credit",
                "amount": fee,
            },
        ],
        idempotency_key=f"wd:{request.id}:service-fee",
        operation_type="withdrawal_fee",
        operation_id=str(request.id),
    )
    request.service_fee_charged = True
    request.save(update_fields=["service_fee_charged", "updated_at"])


def _reverse_service_fee(request: WithdrawalRequest) -> None:
    if not request.service_fee_charged:
        return
    original = JournalEntry.objects.filter(
        project=request.project, idempotency_key=f"wd:{request.id}:service-fee"
    ).first()
    if original is not None:
        ledger_services.reverse_entry(
            original=original,
            reason=f"withdrawal {request.id} failed; service fee reversed",
            idempotency_key=f"wd:{request.id}:service-fee:reversal",
        )
    request.service_fee_charged = False
    request.save(update_fields=["service_fee_charged", "updated_at"])


def _emit_withdrawal_terminal(request: WithdrawalRequest) -> None:
    from waas.modules.webhooks import services as webhook_services

    webhook_services.emit_event(
        project=request.project,
        event_type=f"withdrawal.{request.status}",
        data={
            "withdrawal_id": str(request.id),
            "wallet_id": str(request.wallet_id),
            "network": request.network.slug,
            "asset": request.asset.symbol,
            "amount": str(int(request.amount)),
            "destination_address": request.destination_address,
            "tx_hash": request.chain_tx_hash,
            "status_reason": request.status_reason,
        },
    )


# --------------------------------------------------------------- lifecycle


@transaction.atomic
def dispatch_withdrawal(
    *, request: WithdrawalRequest, factories: dispatch.Factories = dispatch.DEFAULT_FACTORIES
) -> WithdrawalRequest:
    """Charge the fee, then run the family pipeline. Called by the
    worker command for approved requests."""
    if request.status != WithdrawalRequest.Status.APPROVED:
        raise OperationsError(f"request is {request.status}, not approved")
    _assert_not_platform_halted(action="withdrawal dispatch")
    if _halt_active(request.network):
        raise OperationsError("network is halted pending reconciliation")
    request.status = WithdrawalRequest.Status.SIGNING
    request.save(update_fields=["status", "updated_at"])
    try:
        _charge_service_fee(request)
    except Exception as exc:  # e.g. fee exceeds the available balance
        request.status = WithdrawalRequest.Status.FAILED
        request.status_reason = f"service fee charge failed: {exc}"[:500]
        request.save(update_fields=["status", "status_reason", "updated_at"])
        _emit_withdrawal_terminal(request)
        return request
    try:
        chain_tx = dispatch.execute(request, factories=factories)
    except GasTopUpPending as exc:
        # Not a failure: a gas top-up is in flight. Return the
        # request to APPROVED (the worker retries it), undo the
        # service-fee charge, and record why it is waiting.
        request.status = WithdrawalRequest.Status.APPROVED
        request.status_reason = f"awaiting gas: {exc.reason}"[:500]
        request.save(update_fields=["status", "status_reason", "updated_at"])
        _reverse_service_fee(request)
        return request
    except Exception as exc:
        # The operations layer is the worker's safety net: a
        # provider or pipeline exception must land the request in
        # a defined terminal state, never crash the batch.
        request.status = WithdrawalRequest.Status.FAILED
        request.status_reason = f"dispatch error: {exc}"[:500]
        request.save(update_fields=["status", "status_reason", "updated_at"])
        _reverse_service_fee(request)
        _emit_withdrawal_terminal(request)
        return request
    family = dispatch.family_of(request.network)
    request.chain_family = family
    request.chain_tx_id = chain_tx.id
    request.chain_tx_hash = dispatch.chain_tx_hash(chain_tx, family)
    status = chain_tx.status
    if status in ("broadcast",):
        request.status = WithdrawalRequest.Status.BROADCAST
    elif status == "dropped":
        request.status = WithdrawalRequest.Status.CONFIRMING
        request.status_reason = "broadcast outcome unknown; tracking"
    elif status == "confirmed":
        request.status = WithdrawalRequest.Status.COMPLETED
    else:  # failed / reverted at the pipeline level
        request.status = WithdrawalRequest.Status.FAILED
        request.status_reason = getattr(chain_tx, "failure_reason", "") or status
        _reverse_service_fee(request)
    request.save(
        update_fields=[
            "chain_family", "chain_tx_id", "chain_tx_hash",
            "status", "status_reason", "updated_at",
        ]
    )
    AuditEvent.record(
        "withdrawal.dispatched",
        actor_user=None,
        organization=request.project.organization,
        project=request.project,
        metadata={
            "request": str(request.id),
            "family": family,
            "chain_status": status,
            "status": request.status,
        },
    )
    if request.status in (WithdrawalRequest.Status.COMPLETED, WithdrawalRequest.Status.FAILED):
        _emit_withdrawal_terminal(request)
    return request


@transaction.atomic
def refresh_withdrawal(
    *, request: WithdrawalRequest, factories: dispatch.Factories = dispatch.DEFAULT_FACTORIES
) -> WithdrawalRequest:
    """Advance an in-flight request from its chain transaction."""
    if request.status not in (
        WithdrawalRequest.Status.BROADCAST,
        WithdrawalRequest.Status.CONFIRMING,
    ):
        return request
    if not request.chain_family or request.chain_tx_id is None:
        return request
    model = dispatch.chain_tx_model(request.chain_family)
    chain_tx = model.objects.filter(id=request.chain_tx_id).first()
    if chain_tx is None:
        return request
    chain_tx = dispatch.confirm(chain_tx, network=request.network, factories=factories)
    request.chain_tx_hash = dispatch.chain_tx_hash(chain_tx, request.chain_family) or request.chain_tx_hash
    if chain_tx.status == "confirmed":
        request.status = WithdrawalRequest.Status.COMPLETED
        fee = dispatch.chain_tx_fee(chain_tx, request.chain_family)
        if fee is not None:
            request.actual_fee = fee
            request.fee_asset = Asset.objects.filter(
                network=request.network, token_standard="native"
            ).first()
    elif chain_tx.status == "reverted":
        request.status = WithdrawalRequest.Status.FAILED
        request.status_reason = getattr(chain_tx, "failure_reason", "") or "reverted on-chain"
        _reverse_service_fee(request)
    else:
        request.status = WithdrawalRequest.Status.CONFIRMING
    request.save(
        update_fields=[
            "chain_tx_hash", "status", "status_reason",
            "actual_fee", "fee_asset", "updated_at",
        ]
    )
    if request.status in (WithdrawalRequest.Status.COMPLETED, WithdrawalRequest.Status.FAILED):
        AuditEvent.record(
            f"withdrawal.{request.status}",
            actor_user=None,
            organization=request.project.organization,
            project=request.project,
            metadata={"request": str(request.id), "actual_fee": str(request.actual_fee)},
        )
        _emit_withdrawal_terminal(request)
    return request


# ----------------------------------------------------------------- refunds


@transaction.atomic
def record_refund(
    *, request: WithdrawalRequest, amount: int, actor, reason: str
) -> WithdrawalRequest:
    """Operational refund playbook: credit a completed withdrawal
    back to the customer as an explicit ADJUSTMENT journal (e.g.
    the destination returned the funds, or an operations error is
    being corrected). True single-entry reversals stay available
    via the ledger's reverse_entry; a refund spans the settlement,
    so it is booked as its own balanced adjustment. Never edits
    history."""
    if request.status != WithdrawalRequest.Status.COMPLETED:
        raise OperationsError("only completed withdrawals can be refunded")
    if amount <= 0 or int(request.refunded_amount) + amount > int(request.amount):
        raise OperationsError("refund exceeds the unrefunded remainder")
    scope = request.wallet.external_customer_id or f"wallet:{request.wallet.id}"
    count = JournalEntry.objects.filter(
        project=request.project,
        idempotency_key__startswith=f"wd:{request.id}:refund:",
    ).count()
    ledger_services.post_journal(
        project=request.project,
        asset=request.asset,
        entry_type=JournalEntry.EntryType.ADJUSTMENT,
        lines=[
            {
                "account": ledger_services.get_or_create_account(
                    project=request.project,
                    asset=request.asset,
                    account_type=AccountType.CUSTODY_ONCHAIN,
                ),
                "side": "debit",
                "amount": amount,
            },
            {
                "account": ledger_services.get_or_create_account(
                    project=request.project,
                    asset=request.asset,
                    account_type=AccountType.CUSTOMER_AVAILABLE,
                    external_ref=scope,
                ),
                "side": "credit",
                "amount": amount,
            },
        ],
        idempotency_key=f"wd:{request.id}:refund:{count + 1}",
        operation_type="withdrawal_refund",
        operation_id=str(request.id),
        reason=reason,
    )
    request.refunded_amount = int(request.refunded_amount) + amount
    request.save(update_fields=["refunded_amount", "updated_at"])
    AuditEvent.record(
        "withdrawal.refunded",
        actor_user=actor,
        organization=request.project.organization,
        project=request.project,
        metadata={"request": str(request.id), "amount": str(amount), "reason": reason},
    )
    return request


# ------------------------------------------------------------------ halts


def apply_reconciliation_report(*, network: BlockchainNetwork, report: dict) -> bool:
    """Raise/clear the network halt from a reconciliation report.
    Returns True if the network is halted after this call."""
    unbalanced = [a for a in report.get("assets", []) if not a["balanced"]]
    halt, _ = ReconciliationHalt.objects.get_or_create(network=network)
    if unbalanced:
        halt.active = True
        halt.reason = "; ".join(
            f"{a['asset']}: expected {a['expected_custody']} vs ledger {a['ledger_custody']}"
            for a in unbalanced
        )
        halt.raised_at = timezone.now()
        halt.cleared_at = None
        halt.save()
        return True
    if halt.active:
        halt.active = False
        halt.cleared_at = timezone.now()
        halt.save()
    return False


# ----------------------------------------------------------------- exports


def export_journal_csv(*, project: Project, days: int = 30) -> str:
    """Finance export: journal entries with their lines for a
    project, as CSV (integer amounts, ISO timestamps)."""
    since = timezone.now() - timedelta(days=days)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "entry_id", "created_at", "entry_type", "asset", "operation_type",
            "operation_id", "idempotency_key", "account_type", "external_ref",
            "side", "amount",
        ]
    )
    entries = (
        JournalEntry.objects.filter(project=project, created_at__gte=since)
        .select_related("asset")
        .prefetch_related("lines__account")
        .order_by("created_at", "id")
    )
    for entry in entries:
        for line in entry.lines.all():
            writer.writerow(
                [
                    str(entry.id),
                    entry.created_at.isoformat(),
                    entry.entry_type,
                    entry.asset.symbol,
                    entry.operation_type,
                    entry.operation_id,
                    entry.idempotency_key,
                    line.account.account_type,
                    line.account.external_ref,
                    line.side,
                    str(int(line.amount)),
                ]
            )
    return out.getvalue()
