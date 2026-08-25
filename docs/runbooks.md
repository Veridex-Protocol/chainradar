# Ashinity Engine Operational Runbooks

This document defines the 10 standard operating procedures (SOPs) for maintaining data integrity, verifier safety, source health, and compliance.

---

## Runbook 1: Source Parser Breaks
- **Trigger**: Collector fails JSON/HTML schema validation; `consecutive_failures >= 3`.
- **Immediate Action**:
  1. Freeze cursor advancement for `source_id` in `source_cursors` table.
  2. Save raw unparsed response payload to `<object_store>/quarantine/`.
  3. Emit low-severity alert to `#source-health`.
- **Recovery**:
  1. Inspect payload diff against expected parser version in `src/collectors/`.
  2. Update normalizer or regex extractor; add fixture to `tests/fixtures/`.
  3. Run test suite: `pytest tests/test_collectors.py`.
  4. Deploy patch and replay from last safe cursor timestamp.

---

## Runbook 2: Rate Limit Exhausted (HTTP 429)
- **Trigger**: Upstream API returns HTTP 429 or `Retry-After` header.
- **Immediate Action**:
  1. Pause collector execution immediately until `reset_at` timestamp.
  2. Do not advance cursor; preserve current safe SHA.
  3. Reduce query frequency or token bucket burst capacity in `config/source_register.yaml`.
- **Recovery**:
  1. Resume polling automatically upon rate reset.
  2. Verify no evidence was dropped during hiatus.

---

## Runbook 3: Upstream Registry Rewrites History (Git Rebase / Force Push)
- **Trigger**: Registry commit hash cannot be resolved via linear fast-forward git log.
- **Immediate Action**:
  1. Compare immutable last-known `safe_sha` against upstream HEAD.
  2. Log a `source_anomaly_event` in the audit log.
  3. **Never delete** existing rows in the `evidence_events` ledger.
- **Recovery**:
  1. Re-clone registry repository shallowly.
  2. Execute idempotent reconciliation; only append new observations.

---

## Runbook 4: Candidate Identity Mismatch
- **Trigger**: Probe returns chain ID or genesis hash differing from published claim.
- **Immediate Action**:
  1. Set candidate state to `QUARANTINED` / `RADAR`.
  2. Block promotion to Outreach queue; apply +30 risk penalty.
  3. Log incident in `audit_logs` with before/after probe hashes.
- **Recovery**:
  1. Re-probe independent RPC endpoint.
  2. Human analyst reviews official documentation to confirm network migration or spoofing attempt.

---

## Runbook 5: Testnet Reset
- **Trigger**: Same chain ID / network environment observes a new genesis hash.
- **Immediate Action**:
  1. Mark old `NetworkIncarnation` as `SUPERSEDED` (`superseded_by_id = new_incarnation_id`).
  2. Create new active `NetworkIncarnation` row.
  3. Retain complete historical evidence link and timeline.
- **Recovery**:
  1. Re-verify liveness and advancing block height from block 0.
  2. Emit notification in daily digest under "Testnet Resets & Upgrades".

---

## Runbook 6: False HOT Alert
- **Trigger**: Candidate promoted to HOT without genuine public chain or Africa readiness.
- **Immediate Action**:
  1. Analyst rejects candidate in dashboard with reason code (e.g. `TOKEN_ONLY`, `DAPP_ONLY`, `MISLEADING_CLAIM`).
  2. Pipeline moves state to `REJECT` and applies suppression.
- **Recovery**:
  1. Extract offending text snippet and add to negative test corpus.
  2. Calibrate confidence/risk weights in `config/default_config.yaml`.
  3. Rerun temporal backtest: `pytest tests/test_backtest_engine.py`.

---

## Runbook 7: Missed Known Chain
- **Trigger**: A public chain reaches mainnet without prior engine detection.
- **Immediate Action**:
  1. Trace chain's earliest public trace (PR, repo creation, seed post).
  2. Identify why existing collectors missed the signal (query keyword gap, missing source).
- **Recovery**:
  1. Add source or expand query packs in `config/query_packs.yaml`.
  2. Rerun historical backtest across 50 positive fixtures to measure marginal recall gain.

---

## Runbook 8: Data Subject Request / Opt-Out (NDPA / GDPR)
- **Trigger**: Contact requests removal or opt-out under NDPA GAID 2025 or GDPR.
- **Immediate Action**:
  1. Locate contact record via `POST /api/candidates/{id}/suppress` or `PrivacyComplianceManager.suppress_contact()`.
  2. Delete plaintext personal details (name, email, profile URL).
  3. Retain only irreversible SHA-256 hash in `contacts` table with `suppressed = True`.
- **Recovery**:
  1. Verify contact hash prevents any future outreach generation across all collectors.

---

## Runbook 9: Credential Compromise
- **Trigger**: Leaked API token or unauthorized access detected.
- **Immediate Action**:
  1. Invalidate compromised token immediately in upstream provider console (GitHub, Brave, Neynar).
  2. Update `.env` or cloud secret manager.
  3. Inspect audit log for unauthorized state transitions.
- **Recovery**:
  1. Rotate database and application secret keys.
  2. Restart service containers.

---

## Runbook 10: Platform Terms / API Deprecation
- **Trigger**: Upstream platform changes terms of service or deprecates API endpoints (e.g. Google Search API transition / Bing retirement).
- **Immediate Action**:
  1. Flip kill switch for affected source in `config/source_register.yaml` or via UI.
  2. Ensure downstream pipeline continues running without unhandled exceptions.
- **Recovery**:
  1. Build and test replacement adapter.
  2. Enable new collector in staging before flipping production switch.
