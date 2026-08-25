# Governance artifacts

Spec 23 requires these to exist before the engine processes named contacts or
supports outreach. They are working documents, not boilerplate: the source
register is machine-readable and drives the kill switches in the running
system.

| Artifact | File | Status |
|---|---|---|
| Source register | `../../config/source_register.yaml` + `source-register.md` | Machine-readable, enforced |
| Privacy notice & lawful basis | `privacy-notice.md` | Template — **requires counsel review** |
| Outreach policy | `outreach-policy.md` | Operational |
| Security threat model | `threat-model.md` | Operational |
| Retention schedule | `retention.md` | Enforced via config |
| Audit log | `audit_logs` table | Enforced |

> **Not legal advice.** The privacy and marketing documents are drafting
> starting points. Nigeria's NDP Act/GAID obligations and any recipient-side
> regime (GDPR/UK GDPR/ePrivacy, CAN-SPAM) must be reviewed by qualified
> counsel against the actual deployed workflow before outreach begins.
