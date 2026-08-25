# Source register

The authoritative register is `config/source_register.yaml`, which the running
system reads. Each entry carries owner, terms URL, access method, fields
stored, retention, rate limit, review date and a kill switch.

## Why it is machine-readable

A register that only exists as a document drifts from what the code actually
does. Here, disabling a source in the register disables it in the engine
(`POST /api/sources/{source_id}/toggle_kill_switch`), and the collector reads
its own rate limit from the same row. The compliance artifact and the control
are the same object.

## Tiers and what each source may be used for

A source's job is discovery, verification, enrichment or corroboration — never
all four by assumption (spec 05).

| Tier | Examples | Reliability | May establish |
|---|---|---|---|
| A — direct technical/official | Official repo/config, registry PR, official docs/blog, verified RPC/genesis | High | Official attribution, A1/A2 Africa intent |
| B — ecosystem infrastructure | RaaS, bridge registry, explorer, indexer, oracle | Medium-high | Operational corroboration |
| C — structured commercial | Careers/ATS, grants, accelerator portfolios | Medium | Intent and readiness |
| D — public conversation | Approved social APIs, forums, news/search | Low-medium | Leads only |
| E — market aggregator | Asset platforms, token listings, TVL directories | Medium | Visibility, late corroboration |

Reposts, mirrors and syndications of one press release count as **one** origin.
This is enforced in scoring: corroboration counts distinct source *families*,
never raw event volume.

## Prohibited sources

Absent from the register by design, and not to be added:

- LinkedIn scraping or automation of any kind
- Private Discord/Telegram communities without explicit authorization
- Any source requiring login bypass or access-control circumvention
- Purchased personal-contact databases
- Retired Bing Search APIs (retired 11 Aug 2025); Google Custom Search JSON API
  has a transition deadline of 1 Jan 2027 for existing customers, so new work
  should not be designed around it

## Review cadence

Review each entry quarterly, and immediately on any terms change. External
platforms change their terms and pricing frequently; a source whose terms have
changed is disabled first and re-assessed second.
