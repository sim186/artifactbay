# Foundry &nbsp;<img src="web/public/favicon.svg" alt="" height="28" align="absmiddle" />

Session-centric artifact repository for AI coding agents. See `docs/` for specs.

The mark — **Molten Ember**: a cool indigo vault (the repository) holding a molten lava **F** (the freshly-forged artifact) at its core. Full lockup: [`web/public/logo.svg`](web/public/logo.svg).

## Layout
```
docs/                     specs (API contract, agent protocol)
backend/                  FastAPI + SQLModel API
web/                      Vite + React + TanStack SPA
docker-compose.yml        Postgres for dev (app runs native)
docker-compose.full.yml   whole stack: db + backend + web (nginx)
```

## Dev workflow
Postgres in Docker, app native for hot-reload:
```bash
docker compose up -d                          # Postgres on :5432
cd backend && cp .env.example .env
uv run uvicorn app.main:app --reload          # API on :8000
```
Stop: `docker compose down` (keep data) · `docker compose down -v` (wipe).

## Test
```bash
cd backend && uv run python smoke_test.py     # uses FOUNDRY_DATABASE_URL or SQLite
```

## Full stack (deploy / demo)
Everything in containers, nginx serving the SPA + proxying the API:
```bash
docker compose -p foundry-full -f docker-compose.full.yml up --build -d
#  → http://localhost:8080
# optional demo data (through the nginx proxy):
cd backend && uv run python seed.py http://localhost:8080
```
Use `-p foundry-full` so it doesn't collide with the dev `docker compose` project.
Tear down: `docker compose -p foundry-full -f docker-compose.full.yml down -v`.

## Docker philosophy
- **Dev** = Postgres containerized, backend/frontend native. Fast inner loop.
- **Full** = everything in `docker-compose.full.yml`. The self-hosted deploy path.
- `backend/Dockerfile` (uv multi-stage) + `web/Dockerfile` (node build → nginx).
