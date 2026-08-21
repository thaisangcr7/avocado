# Deploy Avocado on Oracle Always Free (full product)

This is the path that keeps **everything** working — including the analysis
sandbox. Managed free tiers (Render, Railway free, etc.) cannot grant a Docker
socket, so they must disable sandboxed code execution. A permanent free VM does
not have that limit.

## What you get

- Always-on public URL (no 15-minute sleep)
- Same `docker compose` stack as local: API, web, Postgres, Redis, sandbox
- Cited RAG + spreadsheet analysis

## 1. Create the VM

1. Sign up at [Oracle Cloud](https://www.oracle.com/cloud/free/).
2. Create an **Always Free** compute instance:
   - Shape: **VM.Standard.A1.Flex** (Ampere), 2 OCPU / 12 GB RAM if available
   - Image: Ubuntu 22.04 or 24.04
   - Add your SSH public key
3. In the VCN security list / NSG, allow ingress:
   - TCP **22** (SSH)
   - TCP **80** and **443** (HTTP/HTTPS)

Note the public IP.

## 2. Install Docker on the VM

```bash
ssh ubuntu@YOUR_PUBLIC_IP

sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# Log out and back in so the docker group applies
```

## 3. Clone and configure

```bash
git clone https://github.com/YOUR_USER/Avocado.git
cd Avocado
cp .env.example .env
```

Generate and set in `.env`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"  # SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # SANDBOX_AUTH_TOKEN
```

Also set:

- `ANTHROPIC_API_KEY` (required for answers / analysis)
- `OPENAI_API_KEY` if embeddings use OpenAI
- `PUBLIC_WEB_URL=https://your.domain` (or `http://YOUR_PUBLIC_IP` while testing)
- `CORS_ORIGINS` to that same origin
- `AVOCADO_API_BASE_URL` for the frontend container if API and web are split by host

For a single-host compose deploy, local storage is fine if the VM disk
persists. Prefer S3/R2 in production once you have a bucket.

## 4. Build sandbox + start

```bash
docker build -t avocado-sandbox:latest ./sandbox
docker compose up -d
```

Wait until `docker compose ps` shows healthy services, then seed:

```bash
# From a machine that can reach the public API, or on the VM itself:
python3 backend/scripts/generate_demo_data.py --base-url http://localhost:8000
```

Open `http://YOUR_PUBLIC_IP:5173` (or put Caddy/nginx in front on 443).

## 5. HTTPS (recommended)

Put [Caddy](https://caddyserver.com/) or nginx + Let's Encrypt on the VM so
browsers trust the origin. Point a domain A-record at the public IP, then
reverse-proxy to the web and API containers.

## Demo checklist after deploy

1. Sign in → **Northwind HQ**
2. Ask: policies → PTO rollover → empty Sandbox honesty
3. **Analyse** on `revenue_by_region.csv`

## If Oracle signup is blocked

Fall back to any always-on VPS with Docker (Hetzner, DigitalOcean, etc.) —
same steps from §2 onward. Avoid free Render if you need the analysis engine;
use it only for a RAG-only preview (`render.yaml` already sets
`SANDBOX_BACKEND=disabled`).
