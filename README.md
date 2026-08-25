# Early Chain Discovery and Africa Expansion Intelligence Engine

Evidence-first competitive intelligence for detecting public blockchains before
or shortly after mainnet, and classifying their Africa relevance.

Implements the ChainRadar specification v1.0 (19 Aug 2026). Public sources only,
read-only network access, human approval before any outreach.

---

## The one idea

This is an **evidence pipeline, not a search query**. Every candidate, score
and alert resolves back to a timestamped source event held in an append-only
ledger. Classifiers propose; they never overwrite evidence, and a generated
summary can never become evidence for itself.

Three consequences run through the whole codebase:

| Rule | Where it shows up |
|---|---|
| Names and symbols never merge records | `src/core/resolver.py` opens a review task instead |
| Explicit Africa intent ≠ inferred Africa fit | `src/classifiers/africa.py` scores A1/A2 and A3 from different evidence |
| Absence of evidence scores zero | no component defaults to full marks |

---

## Quickstart

```bash
# 1. Datastores (PostgreSQL 16 + Redis)
docker compose up -d

# 2. Python environment
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. Schema (the app refuses to start unless this is at head)
.venv/bin/alembic upgrade head

# 4. Run
.venv/bin/uvicorn src.api.main:app --reload
```

Open http://localhost:8000 for the analyst UI, `/docs` for the API.

Whole stack in containers instead:

```bash
COMPOSE_PROFILES=app docker compose up -d --build
```

### Tests

```bash
.venv/bin/python -m pytest -q
```

Tests run against the PostgreSQL container and build their schema by running
the **real migration chain**, so a broken migration fails the suite rather than
being masked by `create_all()`. Point elsewhere with `TEST_DATABASE_URL`.

---

## Architecture

```
COLLECT ──▶ EVIDENCE ──▶ RESOLVE ──▶ VERIFY ──▶ ACT
registries  append-only  entity graph  read-only  scores, alerts,
code, web   provenance   dedup         RPC        evidence cards
```

| Layer | Module | Responsibility |
|---|---|---|
| Collectors | `src/collectors/` | Registries, GitHub, RSS/sitemaps, ATS boards, web/news, social |
| Evidence | `src/storage/repository.py` | Append-only ledger, content hashing, object store |
| Resolution | `src/core/resolver.py` | Organizations, chains, networks, incarnations, collisions |
| Verification | `src/verifier/` | SSRF-hardened probes for 8 protocol families, liveness |
| Classification | `src/classifiers/` | Africa intent, opportunity type, risk |
| Scoring | `src/scoring/` | Confidence, momentum, risk, Radar/Outreach, hard gate |
| Scheduling | `src/scheduler/cadence.py` | The spec-18 cron table with locks and jitter |
| Analyst surface | `src/api/` | Candidates, evidence cards, review queue, digests |
| Measurement | `src/backtesting/` | Temporal replay, source ablation, calibration |

### Identity

```python
logical_chain_key = stable_uuid(official_org_id, canonical_chain_slug)
network_key       = stable_uuid(logical_chain_key, environment, protocol_namespace)
incarnation_key   = stable_uuid(network_key, verified_genesis_fingerprint)
```

CAIP-2 is the cross-family label, but identity is bound to the technical
fingerprint, because testnets reset and chain IDs get reused. An incarnation is
**only** created from a genesis the verifier actually observed.

---

## Configuration

Nothing operational is hard-coded.

| File | Holds |
|---|---|
| `config/default_config.yaml` | Windows, thresholds, weights, TTLs, verify policy |
| `config/source_register.yaml` | Per-source owner, terms URL, rate limit, kill switch |
| `config/query_packs.yaml` | Search query packs |
| `config/lexicons/*.json` | 54 African countries, regions, blocs, hubs, rails, intent packs |
| `.env` | Credentials and deployment wiring only |

The merged YAML is hashed into `RULE_VERSION`, which is stamped on every score
snapshot. A threshold change is therefore visible in the audit trail, and old
snapshots keep the version that produced them.

---

## Safety posture

The verifier treats every RPC URL as attacker-controlled input:

- every resolved address must be public unicast — one private answer in a
  round-robin record rejects the host;
- connections are **pinned** to the validated IP, with the real hostname
  carried in `Host` and the TLS `sni_hostname` extension, so DNS rebinding
  cannot swap the target between validation and connect while certificate
  verification stays intact;
- IPv4 addresses embedded in IPv6 (`::ffff:`, NAT64, 6to4) are unwrapped and
  judged on their own — `::ffff:169.254.169.254` is a metadata-service request
  wearing a costume;
- bodies are capped **while streaming**, redirects are refused by default and
  re-validated per hop, and each domain has a token bucket, a concurrency cap
  and `Retry-After` handling.

Read-only by construction: no send/submit/sign/trace methods, no port
scanning, no private-community crawling, no LinkedIn, no automated outreach.

---

## Compliance

`docs/governance/` carries the artifacts spec 23 requires: source register,
privacy notice, outreach policy, security threat model, retention schedule.
Suppression is keyed on a hashed channel so an opt-out survives re-ingestion.

Scores are prioritization aids, not investment, legal or security conclusions.

---

## Docs

- `docs/analyst-guide.md` — evidence card, workflow states, daily checklist
- `docs/runbooks.md` — incident response for every automated source
- `docs/deployment.md` — environments, migrations, scaling, observability
- `docs/governance/` — compliance artifacts
