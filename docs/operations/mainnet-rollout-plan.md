# Phased Mainnet Rollout Plan

Status: Phase 12 (2026-11-12) — a **plan**, gated on the
production approval decision described in the backlog. Nothing
here is an approval.

## Preconditions (all mandatory)

1. Independent cryptographic review closed (Phase 3 gate).
2. Independent security review / penetration test with no open
   critical/high findings (Phase 12 backlog).
3. Live testnet soak: funded round-trips on every chain
   (deposit → credit → withdrawal → sweep) with reconciliation
   clean for a sustained window.
4. Key ceremony executed per `key-ceremony.md`, restore drill
   passed.
5. Legal/compliance review for the operating jurisdictions.
6. Named production approval decision, dated and scoped,
   recorded outside this backlog.

## Rollout stages

| Stage | Scope | Caps | Exit to next stage |
|---|---|---|---|
| 0 | Testnets only, internal tenants | n/a | Soak criteria (item 3) met |
| 1 | Mainnet, allow-listed tenants (≤3), ETH/BSC only | Per-withdrawal policy caps at conservative values; daily velocity caps low; approvals_required ≥ 2 for all | 2 weeks clean reconciliation, zero unresolved incidents |
| 2 | + TRON, Solana, TON for allow-listed tenants | Caps raised stepwise (2× per step) | Per-chain soak evidence repeated on mainnet small-value |
| 3 | General availability per plan tiers | Plan quotas + policy caps as the control surface | Ongoing |

## Standing controls during rollout

- **Kill switches**: platform halt (global) + per-network
  reconciliation halts — both tested in drills before Stage 1
  (see incident-response §0/§3).
- **Monitoring**: reconciliation job on a schedule with paging
  on any imbalance; scanner-cursor lag alerts per network;
  webhook dead-letter rate alerts; halt state is a dashboard-
  visible, alarmed condition (any halt activation pages).
- **On-call**: named rotation with authority to activate the
  platform halt without approval (deactivation requires the
  two-operator rule, incident-response §7).
- **Change freeze**: no signer/MPC changes during stages 1–2
  except security fixes through the full review path.

## Rollback

Any stage can return to the previous stage by: platform halt →
tenant communication → per-network caps to zero (policy) →
root cause → resume per §7 unhalt procedure. Funds safety
never depends on new code during an incident: halts and
policies are configuration over already-shipped paths.
