# Operational runbooks

Every automated source has an owner, a health state and a recovery path
(spec 27). Owners are recorded per source in `config/source_register.yaml`.

The engine is designed so that **degradation is visible**: a dead collector
reduces coverage and says so, rather than quietly narrowing what the analysts
see. When responding to any incident below, the first question is always
"what coverage did we lose, and for how long?"

---

## Source parser breaks

**Symptom** — parse-failure rate climbs for one `source_id`; candidates from
that source stop appearing.

1. Freeze the cursor: `POST /api/sources/{source_id}/toggle_kill_switch`.
   The cursor is only advanced after the evidence transaction commits, so it is
   already sitting at the last safe position.
2. Save the raw response. It is already in the object store under the content
   hash recorded on the evidence row — no need to re-fetch.
3. Alert the source owner from the register.
4. Patch the parser **against a fixture built from that saved payload**, and
   add the fixture to the suite so the shape cannot regress.
5. Bump `parser_version`; re-enable the kill switch and replay from the safe
   cursor.

Do not delete the evidence rows the broken parser produced. They record what
was observed; the extracted claims were wrong, the observation was not.

---

## Rate limit exhausted

**Symptom** — `429` responses; `retry_after_until` armed on the domain limiter.

1. The client already honours `Retry-After` per domain and preserves candidate
   state without inferring anything negative about legitimacy.
2. If it persists, reduce cadence or query breadth in
   `config/source_register.yaml` rather than adding parallelism.
3. Raise a coverage-loss note so the gap is visible in the next digest.

Never work around a rate limit by rotating credentials or IPs. That breaches
the platform terms the source register points at.

---

## Registry rewrites history

**Symptom** — a force-push changes commits under a watched path; `last_seen_sha`
no longer resolves.

1. Compare against the immutable last-known SHA stored on the cursor.
2. Create a source anomaly event — this is itself intelligence, and sometimes
   indicates a project retracting a registration.
3. Re-clone and reconcile forward. **Never delete evidence** to make the new
   history line up; the earlier observation genuinely happened.

---

## Candidate identity mismatch

**Symptom** — `identity_mismatch` observation: the endpoint served a different
chain ID than the candidate publishes. A review task is opened automatically.

1. The candidate is quarantined from Outreach by the gate — verify that.
2. Re-probe an **independent** endpoint from a different source. One endpoint
   lying is a different problem from the project's metadata being wrong.
3. Inspect the registry entry and official docs for an explained migration.
4. Resolve the review task with an explicit decision. Until then, no contact.

---

## Testnet reset

**Symptom** — genesis fingerprint changes on an existing network.

Handled automatically: a new incarnation is created, the previous one is marked
`superseded` and linked via `superseded_by_id`, and a
`network_reset_or_collision` review task is opened.

The analyst's job is to decide **which** it was:

- a genuine testnet reset → confirm, keep the logical network row;
- the same chain ID reused by an unrelated network → a collision; split the
  candidates and flag the risk.

History is preserved either way. The timeline on the evidence card shows both
incarnations.

---

## False HOT alert

1. Reason-code the false positive on the candidate.
2. Add it to the labelled corpus in `tests/fixtures/sample_data.py`.
3. Evaluate the proposed feature or rule change **against the frozen corpus
   before deploying it** — `run_source_ablation` and `run_cutoff_sweep` will
   show whether the fix costs recall elsewhere.
4. Ship the change as a config version bump so the new `RULE_VERSION` appears
   on subsequent snapshots and the before/after is auditable.

---

## Missed known chain

1. Identify the earliest eligible **public** signal. If there was none, the
   engine was correct to miss it: no system discovers a genuinely stealth chain.
2. If there was one, find which source family carried it and why it did not
   produce a candidate — missing source, query gap, or a gate that was too
   strict.
3. Add the source/query/feature, then run the temporal backtest and source
   ablation to confirm the change buys recall without buying false positives.

---

## Data request / opt-out

1. Locate contact and evidence records for the subject.
2. `POST /api/contacts/suppress` with the channel value. Suppression is keyed
   on the **hashed** channel, so it survives re-ingestion — a source
   republishing the address cannot bring it back into outreach.
3. Apply deletion or restriction as required by the applicable regime.
4. Retain the minimal hashed suppression record. That record exists precisely
   to honour the request and is the lawful minimum needed to prevent
   re-contact.

---

## Credential compromise

1. Disable the affected source immediately (kill switch).
2. Rotate the secret in the secret manager. Credentials never live in the
   repository or in evidence payloads, and URLs are redacted before storage,
   so the blast radius is the credential itself.
3. Review access logs; invalidate tokens.
4. Document the incident, then resume from the stored cursor.

---

## Terms / API change

1. Disable the affected collector by kill switch **first**. Continuing to call
   an API under changed terms is the risk, not the downtime.
2. Review the source register entry: owner, terms URL, fields stored,
   retention.
3. Adapt or replace only through compliant access. If no compliant path
   exists, remove the source and record the coverage loss.

---

## Schema / migration

The service **refuses to start** when the database is not at the migration
head, rather than creating tables itself. If startup fails with a revision
mismatch, run `alembic upgrade head`. This is deliberate: a running instance
silently diverging from the migration history is far harder to debug than a
refusal to boot.
