# Compliance, Platform Terms, and Ethical Boundaries

This document defines the data privacy and regulatory compliance framework for the Ashinity Early Chain Discovery Engine.

---

## 1. Nigeria Data Protection Act (NDPA) & GAID 2025 Compliance
- **Lawful Basis**: Legitimate business interests in competitive market intelligence and technical network telemetry.
- **Data Minimization**:
  - Only public business roles and explicitly published contact channels (e.g. application forms, role-based mailboxes) are collected.
  - Zero scraping of personal social profiles, LinkedIn, or private directories.
- **Data Subject Rights**:
  - Right to object/erase honored within 24 hours.
  - Plaintext data is purged; minimal SHA-256 hash is retained exclusively to prevent future re-contact.
- **Retention**: Active contact records are automatically reviewed and purged after 90 days of inactivity.

---

## 2. GDPR / UK GDPR & US Commercial Regulations
- **B2B Direct Marketing**: All generated outreach briefs require human analyst approval before transmission.
- **CAN-SPAM Compliance**: Mandatory identification of sender, clear business proposition, physical postal address, and one-click opt-out header.
- **No Intrusive Probing**: System performs strictly read-only HTTP GET and JSON-RPC read calls (`eth_chainId`, `eth_blockNumber`, `system_chain`, `getGenesisHash`). No vulnerability testing, port scanning, or credential attacks.

---

## 3. Platform Terms of Service & Crawling Etiquette
- **Robots.txt & Crawl-Delay**: Evaluated and strictly respected for all public web crawling.
- **Conditional Requests**: ETag and `If-None-Match` headers used on 100% of registry and feed requests to conserve bandwidth.
- **Rate Limit Honor**: Automated exponential backoff and jitter per domain.
- **Private Communities**: Zero automated joining or scraping of private Discord, Telegram, or WhatsApp channels.

---

## 4. Source Register Summary

| Source ID | Family | Tier | Terms URL | Fields Stored | Retention | Kill Switch |
|---|---|---|---|---|---|---|
| `ethereum_lists` | Registry | A | https://github.com/ethereum-lists/chains | chainId, RPCs, Explorers, PR author | 365 days | Supported |
| `chainid_network` | Registry | A | https://chainid.network | chainId, RPCs, Faucets | 365 days | Supported |
| `superchain_registry` | Registry | A | https://github.com/ethereum-optimism/superchain-registry | OP Stack config, genesis | 365 days | Supported |
| `cosmos_chain_registry` | Registry | A | https://github.com/cosmos/chain-registry | Cosmos chain.json, APIs, codebase | 365 days | Supported |
| `blockscout_chainscout` | Registry | B | https://docs.blockscout.com | Explorer metadata, RPCs | 365 days | Supported |
| `hyperlane_registry` | Registry | B | https://github.com/hyperlane-xyz | Cross-chain deployments | 365 days | Supported |
| `axelar_configs` | Registry | B | https://github.com/axelarnetwork | Interoperability configs | 365 days | Supported |
| `github_hyper_search` | Code | A | GitHub Terms of Service | Repository metadata, descriptions | 365 days | Supported |
| `rss_sitemaps` | Web | A | Public RSS / Sitemaps | Blog titles, links, summaries | 365 days | Supported |
| `ats_job_boards` | Careers | C | Public ATS feeds (Greenhouse/Lever/Ashby) | Job titles, locations, URLs | 90 days | Supported |
| `bluesky_jetstream` | Social | D | Bluesky Public Terms | Public post excerpts, URIs | 30 days | Supported |
