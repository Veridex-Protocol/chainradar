-- Extensions the engine relies on (spec 19, 21).
--   pg_trgm  : fuzzy analyst search over display names / aliases
--   btree_gin: composite GIN indexes mixing scalar and JSONB columns
-- pgvector is intentionally NOT enabled by default: the spec allows it for
-- analyst search only, never for identity truth.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
