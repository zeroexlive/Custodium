# Key Management — DKG, Share Custody, Lifecycle

Status: Phase 0 — normative design. Companion to
`protocol-evaluation.md` (candidates, both PENDING review) and
`signer-security.md` (what signers check before signing).
No production signing in Phase 1–2.

## 1. Principles

1. **The complete private key never exists.** Not at generation,
   not at signing, not at backup, not at recovery. Any design
   step that assembles a full key — even "briefly, in memory,
   on a trusted box" — is forbidden and is not MPC.
2. **Threshold: 2-of-3.** Each wallet key is shared among three
   signers; any two can sign; one alone learns nothing useful
   and can sign nothing.
3. **Separate custody domains.** The three shares live in three
   administratively and physically separate domains (§3), so a
   single host, cloud account, operator, or network compromise
   yields at most one share.
4. **Shares are never data.** Shares are not rows, files,
   environment variables, secrets in a ticket, or log lines.

## 2. Distributed key generation (DKG)

- Keys are created by a DKG ceremony among the three signer
  services for the chosen protocol (CGGMP21 DKG for ECDSA
  wallets, FROST DKG for Ed25519 wallets). There is no trusted
  dealer by default; a dealer mode requires separate written
  justification and is not the Phase 0 design.
- During DKG each signer receives **only its own share**, plus
  public material: the group public key, public commitments /
  verification shares, and the participant list.
- DKG transcript metadata (wallet id, tenant id, protocol,
  version, participant signer ids, timestamps, success/abort)
  is recorded for audit. Transcript *contents* that would leak
  share material are never recorded.
- A failed or aborted DKG is discarded in full: all partial
  material is destroyed by each participant and a fresh ceremony
  with fresh randomness is required. Partial shares are never
  reused or "completed later".
- The resulting group public key yields the wallet's chain
  addresses through the chain adapters. Address creation after
  DKG follows the HD-derivation limitations in
  `protocol-evaluation.md` §5 — no assumed BIP32 behaviour.

## 3. Share custody

| Domain | Example placement | Operator |
|---|---|---|
| Signer A | Platform cloud, region 1, HSM/KMS-sealed share store | Platform ops |
| Signer B | Platform cloud, region 2 / separate account | Platform ops (separate team/keys) |
| Signer C | Independently administered host / second provider | Separate custodian function |

- Each share is stored encrypted at rest under a domain-local
  key (HSM or KMS in that domain), unlocked only inside the
  signer process for ceremony/signing sessions.
- **No shares in PostgreSQL.** The SaaS database stores wallet
  metadata, public keys, addresses, and policy — never shares,
  never share ciphertext that the database's own credentials
  can decrypt, never seeds.
- **No shares in logs, traces, metrics, crash dumps, support
  bundles, or API responses.** Signing APIs carry payloads and
  signature shares / partial signatures, which are protocol
  values distinct from long-term key shares, and even those are
  never logged at debug level in production configuration.
- Signer hosts have no general-purpose inbound access; they
  accept coordinator connections over mutually authenticated,
  encrypted channels with per-signer identity.
- Operators administer signer hosts without ever being able to
  read a share: administrative access and share access are
  separate capabilities, enforced by the sealing mechanism, not
  by policy statements.

## 4. Signing sessions (key usage)

- Signing is a threshold session coordinated per § signer
  security: signers verify the bound intent before contributing.
- Sessions are single-purpose: one intent, one message digest,
  one session id, bounded lifetime. Session state is never
  reused across intents.
- Protocol-specific secret ephemera (CGGMP21 presignatures,
  FROST nonce shares/commitments) are generated per protocol
  rules, stored with the same custody class as shares while
  alive, used once, and destroyed. Reuse is a critical failure
  and is prevented mechanically (consumed-on-use marking inside
  the signer), not by caller discipline.
- If a session aborts, ephemera for that session are destroyed.
  Retry means a new session with fresh ephemera.

## 5. Lifecycle

```text
DKG → active → (refresh)* → signer replacement (reshare)
     → key rotation (new key, new addresses, funds migration)
     → retirement (signing disabled, shares destroyed after
                  retention/audit conditions are met)
```

- **States are per wallet key**, recorded in metadata (never
  with share material). A wallet whose key is not `active`
  cannot sign; the API surfaces this as an operational state,
  not an error leak.
- **Retirement:** before share destruction, confirm no funds
  remain at the key's addresses and no in-flight operations
  reference it. Destruction is per-domain, attested by each
  custodian, and recorded. Backups age out per §7 — retirement
  is not complete while live backups still hold the shares.

## 6. Refresh and reshare

- **Refresh (same participants, same public key):** CGGMP21 key
  refresh is supported by the candidate implementation; FROST
  refresh follows the pinned implementation's mechanism
  (verified at pinning). Refresh produces new shares for the
  same group public key — wallet addresses do not change.
  Old shares are destroyed by each signer after the refreshed
  set is confirmed; a mixed old/new quorum must never be able
  to sign during the transition window.
- **Schedule:** refresh on a fixed cadence and immediately on
  suspicion of share exposure, personnel change with share-
  domain access, or signer host rebuild.
- **Reshare (participant change):** changing *who* the three
  parties are (not just their share values) is a reshare to a
  new participant set, still 2-of-3, still the same public key
  where the protocol supports it. It follows the replacement
  procedure in §8 and is never an export/import of shares.

## 7. Backup and recovery

- What is backed up: each domain backs up **its own sealed
  share** (ciphertext under that domain's sealing key), plus
  public metadata needed to identify it (wallet id, signer
  index, protocol version).
- There is no backup of "the wallet key". No backup location,
  escrow service, or administrator holds material from two
  domains. Cross-domain backup pooling is forbidden — it
  silently converts 2-of-3 into 1-of-1 at the backup layer.
- Recovery restores one domain's signer from that domain's
  backup into a rebuilt domain with fresh sealing keys
  (rewrap), followed by a refresh (§6) before signing resumes.
- Recovery is a rehearsed procedure: untested backups are
  assumed broken. Restore drills run on testnet wallets on a
  schedule, with results recorded.
- Loss cases: losing one domain entirely is survivable by
  design (2-of-3): the two surviving domains reshare to a new
  third domain (§8). Losing two domains means the key is
  unrecoverable — funds at its addresses are lost. That is the
  accepted threshold trade-off; no backdoor exists to soften
  it, and support staff must never claim otherwise.

## 8. Signer replacement

Trigger: host compromise, custodian change, domain decommission,
or scheduled rotation of infrastructure.

1. Freeze new signing sessions for the affected wallet keys;
   in-flight sessions complete or abort, never migrate.
2. Stand up the replacement signer in its new domain with a
   fresh identity; it starts with **no** share.
3. Run the protocol reshare/refresh ceremony among old quorum
   and the replacement so the replacement receives a fresh
   share and the replaced signer's share becomes useless
   (the share set changes; the old share alone was never
   sufficient, and post-reshare it is not part of any quorum
   for new shares).
4. Confirm signing with a test signature (testnet / sign-verify
   of a harmless digest where the protocol flow allows).
5. Destroy the replaced signer's share and its backups on the
   decommissioned domain, with attestation recorded.
6. Unfreeze. The full sequence is audit-logged as one operation.

At no step is a share copied from one domain to another: the
replacement's share is newly generated by the ceremony.

## 9. Personnel and process controls

- No single person holds administrative control of two share
  domains. Domain administration rosters are disjoint by design
  and reviewed when personnel change (leavers trigger refresh).
- Ceremonies (DKG, refresh, reshare, retirement) require an
  operation record: who initiated, who approved, which wallets,
  when, outcome. The SaaS approval for a ceremony and the
  cryptographic participation are separate acts by separate
  components.
- Break-glass: there is no break-glass key. Emergency action is
  limited to *stopping* signing (freeze), which any one domain
  or the coordinator can effect, never to *enabling* signing
  outside the threshold.

## 10. What Django (the SaaS backend) holds

Public keys, addresses, wallet/tenant metadata, policies,
intents, session coordination state, and audit records. It
holds no shares, cannot decrypt any share store, and its total
compromise yields an attacker the ability to *request*
signatures — which `signer-security.md` exists to defeat —
but never the ability to extract key material.
