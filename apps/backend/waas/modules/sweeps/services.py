"""Phase 10 sweep services: endpoint registration with audited
history, the sweep lifecycle, and approval handling.

Fail-closed throughout: any resolution or validation problem
ends the sweep in a terminal state with the stage recorded.
There is no fallback destination and no re-resolution after
approval (sweep-resolver.md §7).
"""

from __future__ import annotations

import hashlib

from django.db import transaction

from waas.modules.assets.models import Asset
from waas.modules.audit.models import AuditEvent
from waas.modules.blacklist import services as blacklist_services
from waas.modules.ledger import services as ledger_services
from waas.modules.ledger.models import AccountType
from waas.modules.networks.models import BlockchainNetwork
from waas.modules.operations import dispatch
from waas.modules.operations import services as operations_services
from waas.modules.operations.models import ReconciliationHalt
from waas.modules.organizations.models import Membership
from waas.modules.projects.models import Project
from waas.modules.wallets.models import Wallet
from waas.security.secret_management.crypto import decrypt_secret, encrypt_secret

from . import resolver
from .models import (
    ResolvedDestinationSnapshot,
    Sweep,
    SweepApproval,
    SweepDestinationEndpoint,
    SweepEndpointHistory,
    SweepPolicy,
)

ENDPOINT_ADMIN_ROLES = {Membership.Role.OWNER, Membership.Role.ADMINISTRATOR}
SWEEP_REQUESTER_ROLES = ENDPOINT_ADMIN_ROLES | {Membership.Role.FINANCE_OPERATOR}


class SweepError(Exception):
    """A business-rule refusal."""


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


# ------------------------------------------------------------ registration


@transaction.atomic
def register_endpoint(
    *,
    project: Project,
    url: str,
    actor,
    enabled: bool = True,
    signing_secret: str = "",
    dns_resolver=resolver.default_dns_resolver,
) -> SweepDestinationEndpoint:
    resolver.validate_endpoint_url(url, dns_resolver=dns_resolver)
    endpoint = SweepDestinationEndpoint.objects.filter(project=project).first()
    if endpoint is None:
        endpoint = SweepDestinationEndpoint.objects.create(
            project=project,
            url=url,
            enabled=enabled,
            signing_secret_ciphertext=encrypt_secret(signing_secret) if signing_secret else "",
            updated_by=actor if hasattr(actor, "id") else None,
        )
        action = "registered"
        previous_hash = ""
    else:
        previous_hash = _url_hash(endpoint.url)
        endpoint.url = url
        endpoint.enabled = enabled
        if signing_secret:
            endpoint.signing_secret_ciphertext = encrypt_secret(signing_secret)
        endpoint.version += 1
        endpoint.updated_by = actor if hasattr(actor, "id") else None
        endpoint.save()
        action = "updated" if enabled else "disabled"
    SweepEndpointHistory.objects.create(
        endpoint=endpoint,
        actor_id=str(getattr(actor, "id", "")),
        action=action,
        previous_url_hash=previous_hash,
        new_url_hash=_url_hash(url),
    )
    AuditEvent.record(
        "sweep_endpoint.registered",
        actor_user=actor if hasattr(actor, "id") else None,
        organization=project.organization,
        project=project,
        metadata={"action": action, "version": endpoint.version, "url_hash": _url_hash(url)},
    )
    return endpoint


@transaction.atomic
def disable_endpoint(*, project: Project, actor) -> SweepDestinationEndpoint | None:
    endpoint = SweepDestinationEndpoint.objects.filter(project=project).first()
    if endpoint is None:
        return None
    endpoint.enabled = False
    endpoint.version += 1
    endpoint.save(update_fields=["enabled", "version", "updated_at"])
    SweepEndpointHistory.objects.create(
        endpoint=endpoint,
        actor_id=str(getattr(actor, "id", "")),
        action="disabled",
        previous_url_hash=_url_hash(endpoint.url),
        new_url_hash=_url_hash(endpoint.url),
    )
    AuditEvent.record(
        "sweep_endpoint.disabled",
        actor_user=actor if hasattr(actor, "id") else None,
        organization=project.organization,
        project=project,
        metadata={"version": endpoint.version},
    )
    return endpoint


def get_endpoint(project: Project) -> SweepDestinationEndpoint | None:
    return SweepDestinationEndpoint.objects.filter(project=project).first()


def test_resolution(
    *, project: Project, network: BlockchainNetwork, asset: Asset, **resolver_kwargs
) -> resolver.ResolvedDestination:
    """The console test tool: a fresh resolution whose result is
    reported to the caller and NEVER stored as a snapshot or
    reused by any sweep (§2)."""
    endpoint = get_endpoint(project)
    if endpoint is None:
        raise resolver.ResolutionError("not_registered", "no sweep endpoint registered")
    if not endpoint.enabled:
        raise resolver.ResolutionError("disabled", "sweep endpoint is disabled")
    secret = (
        decrypt_secret(endpoint.signing_secret_ciphertext)
        if endpoint.signing_secret_ciphertext
        else ""
    )
    result = resolver.resolve_destination(
        endpoint_url=endpoint.url,
        signing_secret=secret,
        network=network,
        asset=asset,
        request_id=f"test:{project.id}:{network.slug}",
        **resolver_kwargs,
    )
    AuditEvent.record(
        "sweep_endpoint.tested",
        actor_user=None,
        organization=project.organization,
        project=project,
        metadata={"network": network.slug, "address": result.address},
    )
    return result


# ------------------------------------------------------------------ sweeps


@transaction.atomic
def create_sweep(
    *,
    wallet: Wallet,
    network: BlockchainNetwork,
    asset: Asset,
    idempotency_key: str,
    external_reference: str = "",
    requested_by_type: str = "api",
    requested_by_id: str = "",
) -> Sweep:
    from waas.modules.operations.models import PlatformHalt

    if PlatformHalt.is_active():
        raise SweepError("sweep creation refused: platform halt is active (kill switch)")
    project = wallet.project
    existing = Sweep.objects.filter(
        project=project, idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        return existing
    if asset.network_id != network.id:
        raise SweepError("asset does not belong to the network")
    policy = SweepPolicy.objects.filter(project=project).first()
    if policy is not None and not policy.enabled:
        raise SweepError("sweeping is disabled for this project")
    sweep = Sweep.objects.create(
        project=project,
        wallet=wallet,
        network=network,
        asset=asset,
        external_reference=external_reference,
        idempotency_key=idempotency_key,
        requested_by_type=requested_by_type,
        requested_by_id=requested_by_id,
    )
    AuditEvent.record(
        "sweep.created",
        actor_user=None,
        organization=project.organization,
        project=project,
        metadata={
            "sweep": str(sweep.id), "network": network.slug,
            "asset": asset.symbol, "actor": f"{requested_by_type}:{requested_by_id}",
        },
    )
    return sweep


def _fail(sweep: Sweep, status: str, reason: str) -> Sweep:
    sweep.status = status
    sweep.status_reason = reason[:500]
    sweep.save(update_fields=["status", "status_reason", "updated_at"])
    if status == Sweep.Status.FAILED:
        _emit_sweep_terminal(sweep)
    return sweep


def _emit_sweep_terminal(sweep: Sweep) -> None:
    from waas.modules.webhooks import services as webhook_services

    snapshot = ResolvedDestinationSnapshot.objects.filter(sweep=sweep).first()
    webhook_services.emit_event(
        project=sweep.project,
        event_type=f"sweep.{sweep.status}",
        data={
            "sweep_id": str(sweep.id),
            "wallet_id": str(sweep.wallet_id),
            "network": sweep.network.slug,
            "asset": sweep.asset.symbol,
            "amount": str(int(sweep.amount)) if sweep.amount is not None else None,
            "destination_address": snapshot.destination_address if snapshot else None,
            "tx_hash": sweep.chain_tx_hash,
            "status_reason": sweep.status_reason,
        },
    )


@transaction.atomic
def process_sweep(
    *,
    sweep: Sweep,
    factories: dispatch.Factories = dispatch.DEFAULT_FACTORIES,
    resolver_kwargs: dict | None = None,
) -> Sweep:
    """Advance a sweep from `created` (or `awaiting_approval`
    after quorum) as far as possible. Resolution happens exactly
    once, here, before approval; after approval the snapshot is
    the only destination (§7)."""
    resolver_kwargs = resolver_kwargs or {}
    from waas.modules.operations.models import PlatformHalt

    if PlatformHalt.is_active() and sweep.status in (
        Sweep.Status.CREATED, Sweep.Status.RESOLVED
    ):
        return _fail(
            sweep, Sweep.Status.FAILED,
            "platform halt activated before processing (kill switch)",
        )
    if sweep.status == Sweep.Status.CREATED:
        sweep.status = Sweep.Status.RESOLVING
        sweep.save(update_fields=["status", "updated_at"])
        endpoint = get_endpoint(sweep.project)
        if endpoint is None:
            return _fail(sweep, Sweep.Status.RESOLUTION_FAILED, "no endpoint registered")
        if not endpoint.enabled:
            return _fail(sweep, Sweep.Status.RESOLUTION_FAILED, "endpoint disabled")
        secret = (
            decrypt_secret(endpoint.signing_secret_ciphertext)
            if endpoint.signing_secret_ciphertext
            else ""
        )
        request_id = f"swp:{sweep.id}"
        try:
            result = resolver.resolve_destination(
                endpoint_url=endpoint.url,
                signing_secret=secret,
                network=sweep.network,
                asset=sweep.asset,
                request_id=request_id,
                **resolver_kwargs,
            )
        except resolver.ResolutionError as exc:
            AuditEvent.record(
                "sweep.resolution_failed",
                actor_user=None,
                organization=sweep.project.organization,
                project=sweep.project,
                metadata={"sweep": str(sweep.id), "stage": exc.stage, "error": exc.message},
            )
            return _fail(
                sweep, Sweep.Status.RESOLUTION_FAILED, f"{exc.stage}: {exc.message}"
            )
        ResolvedDestinationSnapshot.objects.create(
            sweep=sweep,
            destination_address=result.address,
            normalized_address=result.normalized,
            endpoint_url_hash=_url_hash(endpoint.url),
            request_id=request_id,
            raw_body_sha256=result.raw_body_sha256,
        )
        sweep.status = Sweep.Status.RESOLVED
        sweep.save(update_fields=["status", "updated_at"])
        # Policy checks against the snapshot (§8.2).
        if blacklist_services.is_blacklisted(
            address=result.address, network=sweep.network, project=sweep.project
        ):
            return _fail(sweep, Sweep.Status.POLICY_DENIED, "destination is blacklisted")
        own = {
            row.normalized_address
            for row in sweep.wallet.addresses.filter(network=sweep.network)
        }
        if result.normalized in own:
            return _fail(
                sweep, Sweep.Status.POLICY_DENIED, "destination is one of the wallet's own addresses"
            )
        if ReconciliationHalt.objects.filter(network=sweep.network, active=True).exists():
            return _fail(sweep, Sweep.Status.FAILED, "network halted pending reconciliation")
        # Amount discovery: available minus leave-behind.
        sweep_policy = SweepPolicy.objects.filter(project=sweep.project).first()
        leave = int(sweep_policy.leave_behind) if sweep_policy else 0
        threshold = int(sweep_policy.min_sweep_threshold) if sweep_policy else 0
        scope = sweep.wallet.external_customer_id or f"wallet:{sweep.wallet.id}"
        account = ledger_services.get_or_create_account(
            project=sweep.project,
            asset=sweep.asset,
            account_type=AccountType.CUSTOMER_AVAILABLE,
            external_ref=scope,
        )
        sweepable = ledger_services.account_balance(account) - leave
        if sweepable < max(threshold, 1):
            sweep.amount = 0
            sweep.status = Sweep.Status.COMPLETED
            sweep.status_reason = "below threshold: nothing to sweep"
            sweep.save(update_fields=["amount", "status", "status_reason", "updated_at"])
            _emit_sweep_terminal(sweep)
            return sweep
        sweep.amount = sweepable
        # Business quorum from the Phase 9 policy, if any.
        withdrawal_policy = operations_services.resolve_policy(
            project=sweep.project, asset=sweep.asset
        )
        required = (
            0
            if sweepable <= int(withdrawal_policy.auto_approve_below)
            else int(withdrawal_policy.approvals_required)
        )
        sweep.approvals_required = required
        if required > 0:
            sweep.status = Sweep.Status.AWAITING_APPROVAL
            sweep.save(update_fields=["amount", "approvals_required", "status", "updated_at"])
            return sweep
        sweep.save(update_fields=["amount", "approvals_required", "updated_at"])
    if sweep.status in (Sweep.Status.RESOLVED, Sweep.Status.AWAITING_APPROVAL):
        if sweep.status == Sweep.Status.AWAITING_APPROVAL:
            return sweep  # waiting for quorum; record_sweep_approval re-enters
        return _execute_sweep(sweep=sweep, factories=factories)
    return sweep


@transaction.atomic
def _execute_sweep(
    *, sweep: Sweep, factories: dispatch.Factories = dispatch.DEFAULT_FACTORIES
) -> Sweep:
    snapshot = ResolvedDestinationSnapshot.objects.filter(sweep=sweep).first()
    if snapshot is None:
        # Signing without a snapshot is unreachable by
        # construction; if it is ever attempted, fail loudly (§4).
        return _fail(sweep, Sweep.Status.FAILED, "no destination snapshot — signing refused")
    sweep.status = Sweep.Status.SIGNING
    sweep.save(update_fields=["status", "updated_at"])
    try:
        chain_tx = dispatch.execute_transfer(
            wallet=sweep.wallet,
            network=sweep.network,
            asset=sweep.asset,
            # The snapshot address is the ONLY destination ever
            # passed to the signing pipeline (§8.5 verification:
            # the value signed is the snapshot value, byte-exact).
            to_address=snapshot.destination_address,
            amount=int(sweep.amount or 0),
            idempotency_key=f"swp:{sweep.id}",
            factories=factories,
        )
    except Exception as exc:
        return _fail(sweep, Sweep.Status.FAILED, f"dispatch error: {exc}")
    family = dispatch.family_of(sweep.network)
    sweep.chain_family = family
    sweep.chain_tx_id = chain_tx.id
    sweep.chain_tx_hash = dispatch.chain_tx_hash(chain_tx, family)
    if chain_tx.status == "broadcast":
        sweep.status = Sweep.Status.BROADCAST
    elif chain_tx.status == "dropped":
        sweep.status = Sweep.Status.CONFIRMING
        sweep.status_reason = "broadcast outcome unknown; tracking"
    elif chain_tx.status == "confirmed":
        sweep.status = Sweep.Status.COMPLETED
    else:
        sweep.status = Sweep.Status.FAILED
        sweep.status_reason = getattr(chain_tx, "failure_reason", "") or chain_tx.status
    sweep.save(
        update_fields=[
            "chain_family", "chain_tx_id", "chain_tx_hash",
            "status", "status_reason", "updated_at",
        ]
    )
    AuditEvent.record(
        "sweep.dispatched",
        actor_user=None,
        organization=sweep.project.organization,
        project=sweep.project,
        metadata={
            "sweep": str(sweep.id), "family": family,
            "destination": snapshot.destination_address, "status": sweep.status,
        },
    )
    if sweep.status in (Sweep.Status.COMPLETED, Sweep.Status.FAILED):
        _emit_sweep_terminal(sweep)
    return sweep


@transaction.atomic
def refresh_sweep(
    *, sweep: Sweep, factories: dispatch.Factories = dispatch.DEFAULT_FACTORIES
) -> Sweep:
    if sweep.status not in (Sweep.Status.BROADCAST, Sweep.Status.CONFIRMING):
        return sweep
    if not sweep.chain_family or sweep.chain_tx_id is None:
        return sweep
    model = dispatch.chain_tx_model(sweep.chain_family)
    chain_tx = model.objects.filter(id=sweep.chain_tx_id).first()
    if chain_tx is None:
        return sweep
    chain_tx = dispatch.confirm(chain_tx, network=sweep.network, factories=factories)
    sweep.chain_tx_hash = (
        dispatch.chain_tx_hash(chain_tx, sweep.chain_family) or sweep.chain_tx_hash
    )
    if chain_tx.status == "confirmed":
        sweep.status = Sweep.Status.COMPLETED
    elif chain_tx.status == "reverted":
        sweep.status = Sweep.Status.FAILED
        sweep.status_reason = getattr(chain_tx, "failure_reason", "") or "reverted on-chain"
    else:
        sweep.status = Sweep.Status.CONFIRMING
    sweep.save(update_fields=["chain_tx_hash", "status", "status_reason", "updated_at"])
    if sweep.status in (Sweep.Status.COMPLETED, Sweep.Status.FAILED):
        _emit_sweep_terminal(sweep)
    return sweep


@transaction.atomic
def record_sweep_approval(*, sweep: Sweep, approver, decision: str, note: str = "") -> Sweep:
    if sweep.status != Sweep.Status.AWAITING_APPROVAL:
        raise SweepError(f"sweep is {sweep.status}, not awaiting approval")
    membership = Membership.objects.filter(
        organization=sweep.project.organization, user=approver
    ).first()
    if membership is None or membership.role not in operations_services.APPROVER_ROLES:
        raise SweepError("approver lacks a withdrawal approval role")
    if sweep.requested_by_type == "dashboard" and sweep.requested_by_id == str(approver.id):
        raise SweepError("maker-checker: the requester cannot approve their own sweep")
    if SweepApproval.objects.filter(sweep=sweep, approver=approver).exists():
        raise SweepError("this approver has already decided on this sweep")
    SweepApproval.objects.create(
        sweep=sweep, approver=approver, decision=decision, note=note
    )
    if decision == SweepApproval.Decision.REJECTED:
        sweep.status = Sweep.Status.REJECTED
        sweep.status_reason = f"rejected by approver {approver.id}"
        sweep.save(update_fields=["status", "status_reason", "updated_at"])
        return sweep
    approvals = SweepApproval.objects.filter(
        sweep=sweep, decision=SweepApproval.Decision.APPROVED
    ).count()
    if approvals >= sweep.approvals_required:
        # Back to RESOLVED: the worker executes from the SAME
        # snapshot (never a re-resolution — §7).
        sweep.status = Sweep.Status.RESOLVED
        sweep.save(update_fields=["status", "updated_at"])
    return sweep
