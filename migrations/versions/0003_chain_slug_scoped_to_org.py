"""Scope chain-product slugs to their organization.

A globally unique slug silently prevented two different organizations from each
owning a chain with the same name, and would have surfaced as an integrity
error at ingest time rather than as the analyst review the spec calls for.
Spec 04 keys a chain product on (organization_id, canonical_chain_slug).

Revision ID: 0003_chain_slug_org
Revises: 0002_pg_index_types
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_chain_slug_org"
down_revision = "0002_pg_index_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_chain_products_slug")
        op.execute("ALTER TABLE chain_products DROP CONSTRAINT IF EXISTS chain_products_slug_key")
    op.create_index("ix_chain_products_slug", "chain_products", ["slug"], unique=False)
    op.create_unique_constraint("uq_chain_org_slug", "chain_products", ["organization_id", "slug"])


def downgrade() -> None:
    op.drop_constraint("uq_chain_org_slug", "chain_products", type_="unique")
    op.drop_index("ix_chain_products_slug", table_name="chain_products")
    op.create_index("ix_chain_products_slug", "chain_products", ["slug"], unique=True)
