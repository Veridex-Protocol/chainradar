"""PostgreSQL-specific index types (spec 21).

These cannot be expressed in portable model metadata, so they live here:

* BRIN on the evidence ledger's observed_at - the table is append-only and
  physically ordered by time, which is exactly the case BRIN is built for, at a
  fraction of a btree's size.
* GIN on JSONB and array-ish columns for containment queries.
* pg_trgm on display names for the analyst's fuzzy search. Per spec 19 this
  supports *search*, never identity resolution.

Revision ID: 0002_pg_index_types
Revises: 1e6cb8994a20
"""

from alembic import op

revision = "0002_pg_index_types"
down_revision = "1e6cb8994a20"
branch_labels = None
depends_on = None


INDEXES = [
    # Evidence ledger: time-ordered append-only scan support.
    ("ix_evidence_observed_brin", "CREATE INDEX IF NOT EXISTS ix_evidence_observed_brin "
     "ON evidence_events USING brin (observed_at)"),
    ("ix_evidence_claims_gin", "CREATE INDEX IF NOT EXISTS ix_evidence_claims_gin "
     "ON evidence_events USING gin (extracted_claims jsonb_path_ops)"),

    # Organization: alias containment + fuzzy display-name search.
    ("ix_org_aliases_gin", "CREATE INDEX IF NOT EXISTS ix_org_aliases_gin "
     "ON organizations USING gin (aliases jsonb_path_ops)"),
    ("ix_org_domains_gin", "CREATE INDEX IF NOT EXISTS ix_org_domains_gin "
     "ON organizations USING gin (official_domains jsonb_path_ops)"),
    ("ix_org_github_gin", "CREATE INDEX IF NOT EXISTS ix_org_github_gin "
     "ON organizations USING gin (github_orgs jsonb_path_ops)"),
    ("ix_org_display_trgm", "CREATE INDEX IF NOT EXISTS ix_org_display_trgm "
     "ON organizations USING gin (display_name gin_trgm_ops)"),

    # Chain product: purpose/alias containment + fuzzy name search.
    ("ix_chain_purpose_gin", "CREATE INDEX IF NOT EXISTS ix_chain_purpose_gin "
     "ON chain_products USING gin (purpose_labels jsonb_path_ops)"),
    ("ix_chain_aliases_gin", "CREATE INDEX IF NOT EXISTS ix_chain_aliases_gin "
     "ON chain_products USING gin (aliases jsonb_path_ops)"),
    ("ix_chain_name_trgm", "CREATE INDEX IF NOT EXISTS ix_chain_name_trgm "
     "ON chain_products USING gin (canonical_name gin_trgm_ops)"),

    # Score snapshots: the hot path is "latest snapshot for this candidate".
    ("ix_score_candidate_latest", "CREATE INDEX IF NOT EXISTS ix_score_candidate_latest "
     "ON score_snapshots (candidate_id, calculated_at DESC)"),
    # Partial index serving the analyst queues, which only ever read these two
    # states out of the whole history table.
    ("ix_score_active_states", "CREATE INDEX IF NOT EXISTS ix_score_active_states "
     "ON score_snapshots (state, outreach_score DESC) WHERE state IN ('HOT', 'QUALIFIED')"),

    # Contacts: one row per normalized channel per organization, and a fast
    # suppression lookup that must never be bypassed before outreach.
    ("uq_contact_channel_org", "CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_channel_org "
     "ON contacts (channel_hash, COALESCE(org_id, ''))"),
    ("ix_contact_suppressed", "CREATE INDEX IF NOT EXISTS ix_contact_suppressed "
     "ON contacts (channel_hash) WHERE suppressed = true"),

    # Networks: CAIP-2 is indexed but deliberately NOT unique. EVM chain-ID
    # collisions between unrelated projects are expected (spec 16) and must
    # produce separate incarnations plus a review task, not a constraint error.
    ("ix_network_caip2_lookup", "CREATE INDEX IF NOT EXISTS ix_network_caip2_lookup "
     "ON networks (caip2) WHERE caip2 IS NOT NULL"),

    # Open review tasks are polled constantly by the analyst UI.
    ("ix_review_open", "CREATE INDEX IF NOT EXISTS ix_review_open "
     "ON review_tasks (task_type, created_at DESC) WHERE status = 'open'"),

    # Alert dedup window lookups.
    ("ix_alert_dedup", "CREATE INDEX IF NOT EXISTS ix_alert_dedup "
     "ON alert_dispatches (dedup_key, dispatched_at DESC)"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (used for fast local test runs) has no BRIN/GIN/pg_trgm.
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")
    for _name, ddl in INDEXES:
        op.execute(ddl)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name, _ddl in reversed(INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
