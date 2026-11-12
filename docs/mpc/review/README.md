# Independent Cryptographic Review — Package

Status: **NOT COMMISSIONED.** Prepared in Phase 3 so that commissioning
is a decision, not a project. No Custodium component may be described
as "Security Reviewed" or "Production Approved" until a review under
this scope (or a superseding one) is complete and its findings are
dispositioned.

## Why this exists

Custodium's production signing depends on third-party threshold
cryptography (`cggmp24` for ECDSA, `frost-ed25519` for Ed25519) and on
Custodium's own integration of it (transport, signer isolation,
policy binding, share storage). None of that has been independently
reviewed. Published audits of upstream libraries (Kudelski for the
CGGMP family; NCC Group 2023 for the ZF FROST codebase) cover specific
upstream versions and scopes — in both cases **not** the exact
versions Custodium pins, and never Custodium's integration. The gap
is closed only by a commissioned review of the pinned artifacts and
the integration design.

## Contents

- `scope.md` — the review scope: artifacts, questions, and explicit
  out-of-scope items.
- `evidence-checklist.md` — what Custodium must hand the reviewer,
  and the state of each item.

## Candidate reviewers

Firms with published threshold-signature / MPC review practice, to be
shortlisted by the project owner (no engagement exists today):
Kudelski Security, NCC Group, Trail of Bits, Least Authority,
Zellic. Selection, contracting, and payment are the owner's actions;
engineering's obligation is to keep this package current.

## Rules

- The review covers **pinned versions only** (see
  `../phase-3-evaluation.md` for the pin record). Any version change
  re-opens the question of review coverage.
- Findings are recorded verbatim in this directory when received;
  dispositions (fixed / accepted-risk / disputed) are recorded
  alongside, never silently.
- Until then: production signing stays disabled, the Phase 3 harness
  stays test-only, and external communications must not describe the
  MPC stack as audited or reviewed.
