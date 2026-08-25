# Privacy notice and lawful basis (template)

> **Requires review by qualified privacy counsel before outreach begins.**
> This describes what the system does so that assessment can be grounded in
> the real workflow rather than an idealized one.

## What is processed

Public **business** contact information only:

- role mailboxes, partnership/contact forms, official programme applications;
- a named individual **only** where their business role and contact route are
  publicly disclosed by the organization or by that person for that purpose.

## What is never processed

- Guessed email patterns or algorithmically derived addresses
- Private phone numbers or personal addresses
- Data from logged-in or access-controlled surfaces
- Special-category data, or inferences about individuals beyond their public
  business role
- Anything from a private community

## Purpose and minimization

Purpose: identifying and evaluating potential commercial partnerships with
blockchain organizations, and preparing a relevant, evidence-backed approach.

Each contact record carries its source URL, permitted purpose,
`last_verified_at`, and suppression state. Data not needed for that purpose is
not collected. The audit trail stores the **hash** of a channel, not the
address itself.

## Lawful basis

Where legitimate interests is relied upon, a Legitimate Interests Assessment
must be completed and retained, covering the purpose, necessity, and the
balancing test against the individual's interests.

Jurisdiction-specific obligations to assess:

| Regime | Applies to |
|---|---|
| Nigeria NDP Act / GAID 2025 | The deployment and its data subjects |
| GDPR / UK GDPR / ePrivacy | EU/UK recipients and project jurisdictions |
| CAN-SPAM | US recipients — B2B is **not** automatically exempt |

## Data subject rights

Requests are handled via the runbook in `../runbooks.md`. Suppression is keyed
on a hashed channel so an opt-out survives re-ingestion: a source republishing
an address cannot return it to outreach. The minimal hashed suppression record
is retained precisely to honour the request.

## Retention

See `retention.md`. Business contact data is reviewed after 90 days of
inactivity and deleted when no longer necessary, except suppression records.
