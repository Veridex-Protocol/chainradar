# Analyst guide

The engine's job is to put a defensible, evidence-backed case in front of you.
Your job is to decide what to do about it. It will not contact anyone.

---

## Reading an evidence card

`GET /api/candidates/{id}/evidence_card`

A card answers four questions in order: **why now, why this chain, why Africa,
who can act.**

| Section | What to check |
|---|---|
| Header | Stage, family/stack/layer, `discovered_at` vs `last_verified_at` |
| Why now | What is *new* since the last alert — the reason it surfaced today |
| Identity | CAIP-2, chain ID, genesis fingerprint, live/advancing state |
| Timeline | Claimed vs observed dates, kept separately and labelled |
| Africa | A1–A5 label, score components, verbatim evidence quotes, countries |
| Need | Opportunity type and the evidence behind it |
| People | Public business routes only; no guessed addresses |
| Risk | Identity, liveness, authenticity, data quality, existing coverage |
| Evidence | Clickable origin URLs with observed/published times |

### Timestamps

Never read a single "created" date. The card separates:

- `repo_created_at` — when the repository record appeared; code may have been
  imported later
- `registry_pr_opened_at` — when someone *attempted* registration
- `genesis_time` — the protocol's own start time, where it exposes a
  trustworthy one
- `first_observed_block_at` — when this engine first saw the chain advancing
- `mainnet_live_at` — claimed and observed kept apart

A registry PR date is **not** a chain creation date. If a card seems to show a
project appearing from nowhere, check which timestamp you are reading.

---

## The Africa labels

This is the distinction the whole classifier exists to protect:

| Label | Means | Can be used to say |
|---|---|---|
| **A1** explicit intent | The project officially named Africa or a country alongside a concrete intent | "They are going there" |
| **A2** active regional motion | Repeated regional campaigns, local rails, local-language content | "They are already moving there" |
| **A3** Africa-compatible | *Our* hypothesis that the use case fits | "This would suit that market" — never "they plan to" |
| **A4** no evidence | Nothing found | — |
| **A5** already covered | Verified local team/partners exist | The opportunity is specialist, not market entry |

A1/A2 require an **official** source. A generic "global" statement can never
exceed A3, no matter how strong the payments language. If a card shows A1,
the quotes in the Africa section are your check — read them.

Per-country sub-scores matter: a payments chain may fit Nigeria and Kenya for
different reasons, and the card explains the difference rather than collapsing
it into one continental number.

---

## Funding & Capital Intelligence

The evidence engine extracts and reconciles publicly verifiable funding rounds (`funding_rounds` table and Evidence Cards Section 4):

| Element | Description | Verifiability Rule |
|---|---|---|
| `amount_usd` | Normalized numerical value in USD | Parsed directly from disclosed text; never estimated |
| `amount_as_published` | Exact published string (e.g., "$40 million", "$225M") | Captured verbatim from announcement |
| `lead_investor` | Primary VC leading the round (e.g., Paradigm, Hack VC, Founders Fund) | Extracted with multi-party confirmation |
| `investors` | JSON array of all co-investors | Verbatim list of participating funds |
| `quote` | Direct sentence from press release / SEC filing / article | Mandatory quote proving capital raise |
| `source_url` | Origin publication (TechCrunch, CoinDesk, Bloomberg, PR Newswire) | Clickable URL for analyst audit |

### Recency & Milestone Verification
1. **Recency Prioritization**: Chains with recently announced funding (e.g. Q3 2025 – Present) automatically rank above older or dormant chains across the Web UI, interactive TUI (`chainradar tui`), and CLI (`chainradar list`).
2. **First Seen Date (`first_seen_at`)**: Locked to the earliest verifiable milestone across git commits, testnet announcements, registry PRs, or block genesis.
3. **Traceability**: An `EvidenceEvent` with `source_family="capital"` is linked to every funding round.

---

## Workflow states

```
NEW → VERIFYING → RADAR → QUALIFIED → APPROVED → CONTACTED → ENGAGED
                                   ↘ NURTURE
                                   ↘ REJECTED
```

`POST /api/candidates/{id}/transition`

- **RADAR** — plausible, insufficient for outreach. Watch.
- **QUALIFIED** — passed the hard gate; assess strategic fit.
- **APPROVED** — you have approved a contact or research action.
- **NURTURE** — valid but wrong timing. Define the next trigger.
- **REJECTED** — reason-coded. Evidence is preserved, not deleted.

Workflow state is yours. Rescoring never resets it.

---

## The hard gate

A chain name and a chain ID are not enough. Promotion to Outreach requires all
of:

1. a public-chain claim or an operational public network;
2. an official organization/domain/repository relationship — note that the
   *existence* of an organization record does not count, since one is created
   for every candidate from its own name;
3. either a live technical fingerprint **or** corroboration from two
   independent source families.

When a candidate looks strong but sits in RADAR, read `gate_failures` on the
score. It names exactly which of these is missing.

---

## The review queue

`GET /api/review_tasks?status=open`

These are decisions the engine deliberately refused to make.

| Task type | What happened | What you decide |
|---|---|---|
| `chain_id_collision` | Two organizations claim one CAIP-2 | Same project, or genuinely different chains? |
| `network_reset_or_collision` | Genesis changed on a known network | Testnet reset, or chain-ID reuse? |
| `weak_name_match` | Same normalized name, different organizations | Merge, or keep separate? |
| `identity_mismatch` | Endpoint served a different chain ID than published | Bad endpoint, or wrong metadata? |
| `chain_id_changed` | A network reported a new chain ID | Migration, or error? |

Resolve with `POST /api/review_tasks/{id}/resolve`, giving a reason. The
decision is audited; it does not edit raw evidence.

**Clear identity mismatches and collisions before contacting anyone.**

---

## Score history

`GET /api/candidates/{id}/score_history`

Every rescore appends a snapshot rather than overwriting one, each stamped with
the `rule_version` that produced it. When a score moves, this tells you whether
new evidence arrived or a threshold changed underneath it.

---

## Verification trail

`GET /api/candidates/{id}/verifications`

Liveness is never asserted from one request. Two observations 60–180s apart are
stored and compared; the card shows both heights. If something claims a chain
is advancing, this is where you check.

Endpoints are stored redacted, so provider API keys never appear here.

A failed probe lowers liveness. It is **not** evidence of illegitimacy on its
own — plenty of legitimate early chains have flaky public RPC.

---

## Daily checklist

1. Review HOT alerts and recent raises (Q3 2025–Now), and every identity mismatch, **before** contacting anyone.
2. Confirm the exact official evidence behind any A1/A2 label and the
   opportunity type. Read the quotes, not just the score.
3. Check whether the project already has local staff, partners or community
   managers; update the whitespace evidence. An A5 finding changes the pitch
   entirely.
4. Choose the engagement route and tie the value proposition to the specific
   detected need.
5. Record the outcome, the next trigger date, and any suppression request.
6. Triage source health and parser failures so coverage does not shrink
   silently.

---

## Tooling & Interfaces Guide

### CLI Tool
- `chainradar list` — View all candidates sorted by outreach state and funding recency.
- `chainradar list --recent-funding` — Show only chains with verified funding from Q3 2025 to `date.now`.
- `chainradar scan --source all` — Trigger live collector ingestion runs.
- `chainradar enrich --source funding` — Run public funding round discovery and verifications.
- `chainradar probe --candidate <slug>` — Perform safe SSRF-verified RPC status probes.
- `chainradar report generate` — Compile daily morning analyst digest.

### Terminal UI (TUI)
- Run `chainradar tui` for a persistent full-screen real-time terminal dashboard with KPI funnels, discovery queues, and source health monitors.

### Web Dashboard
- Start FastAPI (`uvicorn src.api.main:app --port 8000`) and Next.js frontend (`cd frontend && npm run dev`).
- Visit `http://localhost:3000` to browse queues, filter by Capital/Africa/Stack, explore the RPC verifier playground, and view full evidence cards.

---

## What the engine will not do

- Contact anyone. It drafts; a human verifies evidence, recipient, proposition
  and applicable rules, then sends.
- Guess an email pattern, scrape LinkedIn, or enter a private Discord/Telegram.
- Infer sale or acquisition intent. `investment_ma` requires an explicit
  public statement.
- Tell you a project is Africa-bound because its language sounded global.

Optimize for relevance and trust, not volume.
