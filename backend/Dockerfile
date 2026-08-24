# Multi-stage: dependencies are installed once into a venv and copied into a
# slim runtime, so the shipped image carries no compilers or build headers.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# curl is here for the container healthcheck below, nothing else.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10000 --create-home appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser . .

USER 10000:10000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/live || exit 1

CMD ["sh", "scripts/start_api.sh"]
