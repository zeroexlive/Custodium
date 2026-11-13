# Commissioning Brief — Independent Security Review (sendable)

**From:** Custodium (William, GitHub `zeroexlive`)
**Subject:** Independent review of threshold-cryptography design,
pinned dependencies, and custody-platform security posture
**Status of the system:** Complete implementation, **not in
production**; production signing is disabled in code pending this
review. Nothing in this engagement is a rubber stamp: the platform
cannot be approved for production until the review closes with no
open critical/high findings and a separate written approval
decision is taken by the owner.

## 1. What we are asking for

Two related engagements, quotable separately or together:

**Engagement A — Threshold cryptography review (design + pins).**
Review of the MPC design and the pinned upstream libraries, per
`docs/mpc/review/scope.md` (§A pins, §B questions). Deliverable: a
written report answering every §B question, with findings rated by
severity, and an explicit statement of whether the pinned versions
and the design are fit to proceed to implementation review.

**Engagement B — Platform security assessment / penetration test.**
Black-box + authenticated testing of the deployed-shape system:
multi-tenant API (HMAC machine auth, JWT dashboard auth), tenant
isolation, the sweep-resolver client (SSRF surface), webhook
delivery, ledger integrity controls (append-only enforcement), the
operator kill switch, and the deployment topology in
`docs/operations/deployment-6-server.md`. Deliverable: findings
report with reproduction evidence and severity ratings, plus a
retest window after remediation.

## 2. What you will receive

Everything in `docs/mpc/review/evidence-checklist.md`, including:

- Pin record and `Cargo.lock` for the MPC workspace; the executed
  evaluation harness (real DKG + threshold signing runs of both
  candidate stacks) with its results and CVE analysis — including
  why `cggmp21` was rejected at any version.
- Phase 0 protocol evaluation and STRIDE threat model.
- Key-management and signer-security designs.
- SBOMs for all three components (`docs/security/sbom/`).
- Full source access to the repository (public) and a walkthrough
  call with the builder.

Known honesty items, stated up front: the production signer
transport/implementation does not exist yet (Phase 3 evaluated the
cryptography; the production path is design-stage — scope §B.5–B.9
are design questions for now and become an implementation review
later); no live-chain verification has been performed; the
platform's own readiness checklist is
`docs/operations/production-readiness-checklist.md`.

## 3. What we need from you in reply

1. Which engagement(s) you are quoting for, and the named
   reviewers' relevant track record (published threshold-crypto
   audits for A; fintech/custody assessments for B).
2. Fixed price or capped time-and-materials, estimated start date,
   and elapsed duration.
3. Your report format, severity taxonomy, and retest policy.
4. Any evidence you require beyond the checklist — we will produce
   it before kickoff or record it as a scope limitation in the
   report itself.

## 4. Ground rules

- Findings are reported to the owner unfiltered; remediation
  responses are appended to the report trail, never edited into
  the reviewer's text.
- The review's conclusions gate a separate production-approval
  decision; a clean report alone does not switch signing on.
- Coordinated disclosure for any upstream-library findings follows
  the upstream projects' policies; we will support notification.
