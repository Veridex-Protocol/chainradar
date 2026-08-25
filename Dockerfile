# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage: resolve dependencies into a virtualenv we can copy verbatim.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Runtime stage.
#
# The verifier treats untrusted RPC URLs as an SSRF surface, so the container
# it runs in is hardened to match (spec 15 "Isolation"): non-root user, no
# build toolchain, and no cloud instance credentials mounted in.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ecd

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=ecd:ecd src/ ./src/
COPY --chown=ecd:ecd config/ ./config/
COPY --chown=ecd:ecd migrations/ ./migrations/
COPY --chown=ecd:ecd alembic.ini pyproject.toml requirements.txt ./

# Evidence payloads are the only path the process needs to write.
RUN mkdir -p /app/data/raw_evidence && chown -R ecd:ecd /app/data

USER ecd

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# The service refuses to start unless the schema is migrated to head, so run
# `alembic upgrade head` (see deploy/README) before or alongside this.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
