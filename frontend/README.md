# ChainRadar Web Dashboard

Next.js 15 + React + Tailwind CSS analyst web application for the **ChainRadar Early Chain Discovery & Africa Expansion Intelligence Engine**.

## Getting Started

### 1. Prerequisites

Ensure the backend FastAPI service is running:

```bash
# In repo root:
source .venv/bin/activate
uvicorn src.api.main:app --reload --port 8000
```

### 2. Run the Development Server

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to explore the dashboard.

---

## Features & Views

- **HOT Outreach Queue**: Priority candidates passing hard gates with live RPC endpoints and strategic traction.
- **Capital Filter**: Filter candidate chains by `⚡ Recent Funding (Q3 2025–Now)`, `💰 All Funded`, or `🔍 Unfunded / Bootstrapped`.
- **Pre-Mainnet & Devnet Watchlists**: Track chains from S0 Research to S5 Early Mainnet.
- **Africa Matrix (54 Markets)**: View geographic expansion signals across A1 (Explicit Intent), A2 (Regional Motion), and A3 (Compatible).
- **Interactive RPC Verifier Playground**: Test and verify public blockchain RPCs with SSRF protection directly in the UI.
- **10-Section Evidence Cards**: Drill into full provenance, timeline, team contacts, verified raises, and why now summaries.
- **Source Health & Digests**: Monitor live collector health and view daily analyst briefs.

