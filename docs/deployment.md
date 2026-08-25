# Deployment

## Requirements

| Component | Version | Notes |
|---|---|---|
| Python | 3.12+ | asyncio throughout |
| PostgreSQL | 16+ | JSONB, `pg_trgm`, `btree_gin`; identity store |
| Redis | 7+ | Production queue/scheduler backend |
| Object storage | S3-compatible | Compressed raw evidence; filesystem in dev |

PostgreSQL is not interchangeable here. The evidence ledger uses a BRIN index
on `observed_at`, GIN indexes on JSONB for containment lookups, and `pg_trgm`
for analyst name search. `pgvector` is optional and, per spec 19, is for
analyst *search* only — never for identity truth.

---

## Local

```bash
docker compose up -d                       # postgres + redis
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn src.api.main:app --reload
```

Host ports are deliberately non-default (`55432`, `56379`) so the stack does
not collide with a PostgreSQL or Redis already running locally.

## Containers

```bash
cp .env.example .env      # fill in credentials
COMPOSE_PROFILES=app docker compose up -d --build
```

`migrate` runs `alembic upgrade head` to completion before `api` starts.

---

## Migrations

The schema is owned by Alembic. The application **verifies** the database is at
head on startup and refuses to boot otherwise — it never calls `create_all()`.
A running instance silently diverging from the migration history is much harder
to diagnose than a refusal to start.

```bash
.venv/bin/alembic upgrade head          # apply
.venv/bin/alembic current               # check
.venv/bin/alembic revision --autogenerate -m "..."
.venv/bin/alembic downgrade -1          # roll back one
```

Migration chain:

| Revision | Contents |
|---|---|
| `initial schema` | 16 tables, constraints, portable indexes |
| `0002_pg_index_types` | BRIN / GIN / `pg_trgm` / partial indexes |
| `0003_chain_slug_org` | Chain slug uniqueness scoped to organization |

PostgreSQL-specific index types live in migrations rather than model metadata,
so the models stay portable while the production database still gets the index
types spec 21 calls for.

### Deploying a migration

1. Apply migrations **before** rolling the application (the new code expects
   head).
2. Both `0002` and `0003` are online-safe on a small dataset. At scale, create
   the GIN/BRIN indexes with `CONCURRENTLY` in a separate transaction — note
   that Alembic's default transactional DDL must be disabled for that.
3. Verify with `alembic current` against the deployed database.

---

## Scaling

The MVP runs APScheduler in-process with PostgreSQL advisory locks per job
window, which is safe to run multi-replica: a second worker that cannot take
the lock skips the window rather than duplicating outbound requests.

For production throughput, move the job bodies behind Celery/Dramatiq/RQ with
Redis. The interfaces are already shaped for it — collectors are replaceable
and the pipeline is driven per batch.

Guidance that matters more than replica count:

- **Per-domain limits are per-process.** Horizontal scaling multiplies your
  effective request rate against a source. Lower `per_domain_rate_per_minute`
  as you add replicas, or move the token bucket into Redis.
- **The liveness recheck must stay a queued job.** It is scheduled 60–180s
  after the first probe; never hold a worker asleep waiting for it.
- Backfill and reconciliation are heavy; keep them on their off-peak WAT slots.

---

## Configuration

Credentials come from the environment; everything operational comes from
`config/*.yaml`. A collector whose credential is absent starts **disabled**
rather than failing mid-request.

The merged YAML is hashed into `RULE_VERSION` and stamped on every score
snapshot, so a threshold change is visible in the audit trail and old snapshots
keep the version that produced them. After changing config, trigger an
asynchronous re-score; do not backfill the new version onto old rows.

---

## Security

The verifier reaches attacker-controlled URLs and is isolated accordingly
(spec 15):

- run it in an egress-restricted container with a read-only filesystem, as a
  non-root user, with **no cloud instance credentials** attached — this is the
  control that turns a hypothetical SSRF into a non-event;
- keep `VERIFIER_ENABLED` available as an incident kill switch;
- set `CORS_ALLOWED_ORIGINS` to the real analyst origins. Never `*`: the API
  is credentialed and internal.

The container in `Dockerfile` drops all capabilities, sets
`no-new-privileges`, and mounts the filesystem read-only apart from the
evidence volume.

---

## Observability

Track, at minimum:

| Signal | Why |
|---|---|
| Source health: poll success, parse success, 304 ratio, lag | Coverage shrinking silently is the main failure mode |
| Rate-limit budget per domain | Predicts source lockout before it happens |
| Verification outcomes by failure class | Distinguishes flaky endpoints from identity problems |
| Dedup rate | A spike means a collector lost its cursor |
| Alert precision | The number the whole system is judged on |
| Open review tasks by type | A growing collision queue means the lexicon or gate needs work |

Targets are in spec 24: Precision@20 ≥ 80%, outreach precision ≥ 85%, Africa
A1/A2 precision ≥ 90%, duplicate rate < 2%, HOT alert latency p95 < 15 min.

Run `run_cutoff_sweep` and `run_source_ablation` before paying for a new data
source; the ablation shows whether a family carries unique recall or duplicates
what you already have.

---

## Backup and retention

- The evidence ledger is the system of record; current state is a derived
  projection and can be rebuilt by the nightly reconciliation job.
- Back up PostgreSQL and the object store together — an evidence row whose
  payload is missing loses its provenance.
- Retention defaults are in `config/default_config.yaml`; see
  `docs/governance/retention.md`.
