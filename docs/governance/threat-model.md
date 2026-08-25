# Security threat model

Scope: collectors, the SSRF-hardened verifier, secret handling, webhook
receipt, and analyst access.

The engine's defining exposure is that **it fetches URLs supplied by the
entities it is investigating**. A chain registry entry is attacker-controlled
input that the system is designed to connect to.

---

## T1 — SSRF via a published RPC endpoint

*An adversary registers a chain whose RPC URL points at internal
infrastructure or a cloud metadata service.*

Controls (`src/verifier/safe_url.py`):

- Scheme allow-list; `http` only for explicitly listed public hosts.
- Port allow-list; no scanning, ever.
- **Every** resolved address must be public unicast. Validating only the first
  answer would let a round-robin record rotate a private target into place.
- IPv4 embedded in IPv6 is unwrapped and judged separately — `::ffff:`,
  NAT64 (`64:ff9b::/96`) and 6to4 (`2002::/16`). Without this,
  `::ffff:169.254.169.254` reaches the metadata service through an IPv4-only
  blocklist.
- Explicit denial of known metadata addresses across AWS/GCP/Azure/Alibaba.
- Fails closed: an unparseable address is treated as blocked.

**Residual risk.** Address-space filtering is a moving target. The control that
actually contains this is deployment: run the verifier in an egress-restricted
container with **no instance credentials attached**, so a successful metadata
request returns nothing worth having.

---

## T2 — DNS rebinding

*A hostname resolves to a public address during validation and a private one
at connect time.*

The connection is **pinned** to an address that was validated: the IP is
substituted into the request URL while the real hostname travels in the `Host`
header and the TLS `sni_hostname` extension. Because `sni_hostname` drives
certificate verification as well as SNI, pinning costs nothing in TLS strength
— a wrong hostname still fails the handshake.

Validation and resolution are repeated before every connection and for every
redirect hop.

---

## T3 — Malicious or oversized responses

*An endpoint returns a decompression bomb or an unbounded stream.*

Bodies are capped **while streaming** and aborted at the cap, rather than
buffered and then measured. Strict JSON/schema validation on parse; response
size and parse failures are recorded as source-quality signals.

---

## T4 — Redirect chains

Redirects are refused by default (`max_redirects: 0`). Where policy enables
them, every hop is re-validated and re-resolved; a hop to a private address is
rejected regardless of the budget remaining.

---

## T5 — Credential exposure

*Provider API keys embedded in RPC URLs leak into logs, evidence or the UI.*

`src/util/redaction.py` redacts credentials, key-like query parameters and
long opaque path segments before storage or logging. Evidence rows and
verification observations store the **redacted** URL; the raw endpoint is only
ever held in memory for the request. Secrets come from the environment or a
secret manager and are never committed.

---

## T6 — Poisoned intelligence

*An adversary manufactures a convincing candidate to consume analyst time, or
impersonates a real project.*

- Names and symbols never auto-merge; weak matches open review tasks.
- The hard gate requires official attribution plus technical verification or
  two independent source families.
- Chain-ID collisions raise a risk signal and a review task rather than
  merging.
- Impersonation indicators and token-only evidence carry risk penalties.
- Reposts of one press release count as one origin, so syndication cannot
  manufacture corroboration.

**Residual risk.** A well-resourced adversary controlling a domain, a
repository and an endpoint can pass the technical gate. Human review before
outreach is the mitigation, which is why it is mandatory.

---

## T7 — Webhook receipt

Inbound webhook payloads are untrusted: validate signatures where the provider
supports them, constrain payload size, and treat any URL inside as
attacker-controlled — subject to the same validation as T1.

---

## T8 — Analyst access

The API exposes contact data and evidence. Restrict `CORS_ALLOWED_ORIGINS` to
real analyst origins (never `*`, which browsers reject with credentials
anyway). Put authentication in front of the API before any production
deployment; the current build assumes a trusted network boundary and this is
the main gap to close before go-live.

All analyst decisions — workflow transitions, Africa overrides, review
resolutions, suppressions — are written to `audit_logs` with actor, timestamp
and reason. Overrides never edit raw evidence.

---

## T9 — Supply chain

Dependencies are pinned in `requirements.txt`. The runtime image drops all
capabilities, sets `no-new-privileges`, runs as a non-root user and mounts the
filesystem read-only apart from the evidence volume.

---

## Out of scope by policy

No vulnerability probing, credential testing, port scanning or disruptive
traffic against any target — including targets that look malicious. The engine
performs passive discovery and read-only reads of published endpoints only.
