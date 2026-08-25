# Retention schedule

Defaults live in `config/default_config.yaml` and are enforced by the engine.

| Data | Policy | Rationale |
|---|---|---|
| Raw public technical/config evidence | 365 days online; archive longer where licensing permits | Defensible history of what was public and when |
| Hashes, provenance, extracted claims | Long-lived | Required to explain first-seen and any decision |
| Public social payloads | Shortest period consistent with platform terms; retain IDs/links when full text cannot be stored | Platform terms usually restrict storage |
| Business contact data | Review after 90 days of inactivity; delete when no longer necessary | Minimization |
| Suppression / opt-out records | Retained as minimal hashed record | Exists solely to prevent re-contact |
| Rejected candidates | Keep reason and strong identifiers; expire weak name-only rejects periodically | Prevents the same noise resurfacing weekly |
| Score snapshots | Retained as history | Calibration, backtesting and audit depend on it |
| Audit logs | Retained per policy | Accountability |

## Notes

**Evidence is append-only.** Retention expiry removes payloads and rows on
schedule; it never rewrites history to make a later observation look
consistent. A deletion is itself recorded.

**Social deletions.** When a post is deleted upstream, availability state is
updated but the stored evidence hash and audit metadata are retained where
retention is lawful — the observation genuinely occurred, and an alert that
cited it must remain explainable.

**Suppression outlives deletion.** Erasing a contact record without retaining
the suppression hash would allow re-ingestion to undo the opt-out. The hash is
the minimum needed to honour the request.
