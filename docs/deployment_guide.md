# Deployment & Operations Guide

## 1. Quickstart (Local Development)

### Prerequisites
- Python 3.12+ (or Python 3.14+)
- SQLite (default) or PostgreSQL 16+

### Setup & Run
```bash
# 1. Clone repository & create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env

# 4. Seed initial candidate dataset (optional)
python3 scripts/seed_demo_data.py

# 5. Run development server
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` in your browser to access the Analyst Dashboard.  
Visit `http://localhost:8000/docs` for interactive OpenAPI specifications.

---

## 2. Production Docker Deployment

### Build & Start with Docker Compose
```bash
docker compose up -d --build
```

### Checking Services & Logs
```bash
# Check running containers
docker compose ps

# Inspect engine logs
docker compose logs -f engine
```

---

## 3. Environment Variables Reference

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | Database connection string (PostgreSQL or SQLite) | `sqlite+aiosqlite:///./data/chains.db` |
| `OBJECT_STORE_PATH` | Local directory for raw gzip payloads | `./data/raw_evidence` |
| `GITHUB_TOKEN` | GitHub Personal Access Token for registry/code discovery | `None` (Optional) |
| `BRAVE_API_KEY` | Brave Search API key for web/news query packs | `None` (Optional) |
| `ALERT_WEBHOOK_URL` | Webhook URL for instant HOT alerts | `None` (Optional) |
| `TIMEZONE_DISPLAY` | Display timezone for analyst UI | `Africa/Lagos` |
| `STORAGE_TIMEZONE` | Internal database timestamp storage timezone | `UTC` |
