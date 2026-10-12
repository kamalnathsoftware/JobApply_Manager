# JobApply Manager

> **Important:** the Playwright worker must run on **your own machine/server** (assisted login needs a
> visible browser, and job sites block cloud IPs). You are responsible for complying with each
> site's terms of service. The app never solves or bypasses CAPTCHAs; it pauses and marks tasks `needs_human`.

Status: milestone 1 (scaffolding, MySQL, auth) done. Full setup docs arrive in milestone 9.

## Quick start (milestone 1)
```bash
cp .env.example .env     # then fill JWT_SECRET and FERNET_KEY (commands are in the file)
docker compose up --build
# API: http://localhost:8000/docs   UI: http://localhost:5173
```

## Tests
```bash
cd backend && python -m venv ../.venv && ../.venv/bin/pip install -r requirements-dev.txt
../.venv/bin/ruff check . && ../.venv/bin/pytest
cd ../frontend && npm install && npm run typecheck
```
