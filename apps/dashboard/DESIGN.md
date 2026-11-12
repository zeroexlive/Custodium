# Custodium Dashboard — Design Direction

Status: Phase 1, applied to layout, tokens and shared UI primitives.

## Inspiration (not a copy)

William provided a reference image of a "Hintora" SaaS finance dashboard
(2026-11-12) and asked us to be *inspired* by it. We borrow only its
design language:

- Soft lavender/periwinkle page canvas with one large, floating white
  dashboard shell (very rounded corners, deep soft shadow).
- Left sidebar inside the shell: logo mark + wordmark at top, a rounded
  search pill (with a `⌘K` hint), then grouped navigation under small
  uppercase section labels.
- The active nav item is a dark (near-black) pill with white text; all
  other items are quiet grey text.
- Content cards are white, generously rounded, bordered with a barely
  visible edge and a soft shadow. Card labels are small and muted; the
  numbers are large, bold and tight.
- Small pills carry status/deltas: black pills for primary emphasis,
  blue for chart/brand accents, soft green for success.
- Tables and lists are airy, with light header rows and rounded
  "View all"-style outline buttons.
- Sans-serif UI type (Inter), mono only for hashes/addresses/amounts.

## What we deliberately do NOT copy

- No brand name, logo, copy, user names, bills, subscriptions or figures
  from the reference. All labels are Custodium's own sections
  (Overview, Organizations, Projects, API Keys, Wallets, Addresses,
  Transaction Explorer, Assets & Networks, Sweeps, Sweep Endpoint,
  Blacklist, Webhooks, Audit Logs).
- No invented financial data. The reference is a mockup with sample
  earnings/spending; Custodium shows only real API data, real counts,
  loading states and honest empty states. Charts appear only when a
  later phase supplies real indexed data behind them.

## Tokens

- Canvas: lavender gradient (`style.css`), dark mode falls back to a
  deep navy canvas.
- Shell radius: `rounded-shell` (1.75rem); cards: `rounded-card` (1rem),
  `shadow-card`; shell: `shadow-shell`.
- Brand blue: `brand-600 #2563eb` for the logo mark, chart accents and
  small action pills. Primary buttons are near-black
  (`gray-900` on white in dark mode), matching the reference's active
  pill — blue is an accent, not the primary button colour.
- Both light and dark themes must remain fully usable; dark mode is not
  an afterthought tint of the light design.

## Components

`Button` (rounded-xl, black primary), `Card` (small muted label + body),
`Badge`, `Input`, `EmptyState` in `src/components/ui/` are the only
places these styles are defined; feature views must use them instead of
re-styling per page.
