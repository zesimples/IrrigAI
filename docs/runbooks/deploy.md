# Deploy runbook

## Prerequisites
- SSH access to the production host
- `.env.production` with current secrets (never commit this file)
- Docker and Docker Compose v2 installed on the host

## Steps

### 1. Pull the latest code
```bash
git pull origin main
```

### 2. Build images
```bash
docker compose build backend frontend
```
Building both ensures the images are ready before any service restart.

### 3. Run database migrations
```bash
docker compose run --rm backend alembic upgrade head
```
Always run migrations **before** restarting the application. The migration must be backward-compatible with the running version.

### 4. Restart services with zero-downtime rolling update
```bash
docker compose up -d --no-deps backend worker frontend
```
`--no-deps` avoids recreating the database/Redis containers unnecessarily.

### 5. Verify health
```bash
curl -sf http://localhost:8000/health | jq .
```
All checks should return `"ok"`. If `db` or `redis` shows `"error"`, stop and investigate before declaring success.

### 6. Smoke-test the UI
Open the app in a browser and verify:
- Login works
- Farm dashboard loads
- At least one recommendation can be generated

### 7. Watch logs for 5 minutes
```bash
docker compose logs -f backend worker
```
Look for unhandled exceptions or repeated errors.

## Rollback
See `rollback.md`.

## Checklist
- [ ] Migrations ran cleanly
- [ ] Health endpoint returns all `"ok"`
- [ ] No new 5xx errors in Prometheus within 5 min
- [ ] UI smoke test passed
