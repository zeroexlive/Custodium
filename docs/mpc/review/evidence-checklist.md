# Evidence Checklist — what the reviewer receives

| # | Item | State (2026-11-12) |
|---|------|--------------------|
| 1 | Pin record: exact crate versions + `Cargo.lock` for the MPC workspace | Ready — `docs/mpc/phase-3-evaluation.md`, `services/mpc/Cargo.lock` |
| 2 | Evaluation harness source + test results (what was actually executed) | Ready — `services/mpc/crates/eval_harness/`, results in the Phase 3 evaluation record |
| 3 | Phase 0 protocol evaluation + threat model (STRIDE T-01–T-19) | Ready — `docs/mpc/protocol-evaluation.md`, `docs/security/threat-model.md` |
| 4 | Key-management and signer-security designs | Ready (design) — `docs/mpc/key-management.md`, `docs/mpc/signer-security.md` |
| 5 | Upstream audit reports (Kudelski CGGMP; NCC FROST 2023) + scope mapping to pinned versions | Partial — reports are public upstream; the scope mapping is in the Phase 3 evaluation record; the mapping's conclusions are exactly what the review must confirm |
| 6 | CVE / advisory watch log for pinned dependencies | Started — Phase 3 evaluation record §CVE watch; needs an owner and a cadence (Phase 12 operationalises) |
| 7 | Production transport + signer implementation | **Implemented 2026-11-13** (post-roadmap, at William's direction) — `services/mpc/crates/signer_service` + `docs/architecture/production-signer.md`; locally tested (three-node DKG/signing, cross-verified, restart persistence). Implementation review is now in scope for Engagement A; activation remains gated off pending that review |
| 8 | Incident-response runbook for key compromise | Draft — `docs/operations/incident-response.md` (Phase 0) |
| 9 | SBOM for the MPC workspace | Not produced — add before commissioning (`cargo auditable` / `cargo sbom` evaluation) |
| 10 | Reproducible build instructions for the MPC workspace | Partial — standard cargo build; GMP backend build prerequisites (C toolchain, m4) recorded in the Phase 3 evaluation record |

Rule: an item marked "Ready (design)" is design evidence only. The
review's implementation-level questions (scope §B.5–B.9) cannot be
closed until the corresponding implementation exists and is itself
handed over.
