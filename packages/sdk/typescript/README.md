# Custodium TypeScript SDK — Planned (Phase 0)

No SDK is implemented yet. This directory is a Phase 0 placeholder.

When implemented, the SDK will:

- Target the OpenAPI contract in `packages/contracts/openapi/` (itself
  not yet published), with types generated from that specification
  where practical.
- Authenticate server-to-server requests with the platform's
  **HMAC-SHA256** scheme — API key ID + method + canonical path/query +
  body digest + timestamp + unique nonce, verified server-side with
  replay protection. See the Phase 0 authentication / API-credential
  design in `docs/api/authentication.md`.
- Be for server-side use with API credentials; dashboard sessions use
  secure cookies instead, and API secrets must never ship to browsers.
