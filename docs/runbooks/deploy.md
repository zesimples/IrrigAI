# Deploy runbook

## Prerequisites
- SSH access to the production host
- `.env` with current production secrets (never commit this file)
- Docker and Docker Compose v2 installed on the host
- `YOUR_DOMAIN` replaced in `nginx/prod.conf`

All commands below use both Compose files. Keep the production override in every
build, migration, restart, and diagnostic command so development ports are never
published accidentally.

## Steps

### 1. Pull the latest code
```bash
git pull origin main
```

### 2. Build images
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build backend worker frontend
```
Building all application images ensures they are ready before any service restart.

### 3. Run database migrations
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head
```
Always run migrations **before** restarting the application. The migration must be backward-compatible with the running version.

### 4. Restart services with zero-downtime rolling update
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps backend worker frontend
```
`--no-deps` avoids recreating the database/Redis containers unnecessarily.

### 5. Verify health
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend \
  python -c "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8000/health')), indent=2))"
```
All checks should return `"ok"`. The backend port is deliberately unavailable on
the host in production; the check runs inside the container. Also verify the public
HTTPS endpoint through nginx.

```bash
curl -sf https://YOUR_DOMAIN/health | jq .
```

### 6. Smoke-test the UI
Open the app in a browser and verify:
- Login works
- Farm dashboard loads
- At least one recommendation can be generated

### 7. Watch logs for 5 minutes
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend worker frontend nginx
```
Look for unhandled exceptions or repeated errors.

## Rollback
See `rollback.md`.

## Checklist
- [ ] Migrations ran cleanly
- [ ] `docker compose ... config` publishes only nginx ports 80/443
- [ ] Health endpoint returns all `"ok"`
- [ ] No new 5xx errors in Prometheus within 5 min
- [ ] UI smoke test passed
