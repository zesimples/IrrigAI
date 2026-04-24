# Rotate secrets runbook

## Secrets inventory

| Variable | Stored in | Rotation impact |
|---|---|---|
| `SECRET_KEY` | `.env.production` | Invalidates all active JWT tokens (all users logged out) |
| `ENCRYPTION_KEY` | `.env.production` | Re-encryption of DB fields required before rotation |
| `OPENAI_API_KEY` | `.env.production` | No user impact; revoke old key in OpenAI portal after deploy |
| `SENTRY_DSN` | `.env.production` | No user impact |
| `PROBE_API_KEY` / `WEATHER_API_KEY` | `.env.production` | Ingestion pauses until new key is live |
| `IRRIWATCH_CLIENT_SECRET` | `.env.production` | Same as above |
| `MYIRRIGATION_PASSWORD` | `.env.production` | Same as above |
| DB password (`irrigai` user) | `.env.production` + `DATABASE_URL` | Service outage during rotation window |

## Rotating `SECRET_KEY` (JWT signing key)

1. Generate a new key:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Update `.env.production` with the new value.
3. Restart the backend:
   ```bash
   docker compose up -d --no-deps backend
   ```
4. All existing JWT tokens are immediately invalid. Users will be prompted to log in again. This is expected.

## Rotating an external API key (OpenAI, IrriWatch, etc.)

1. Generate/obtain the new key from the provider's portal.
2. Update `.env.production`.
3. Restart affected services:
   ```bash
   docker compose up -d --no-deps backend worker
   ```
4. Revoke the old key in the provider's portal only **after** confirming the new key is working.

## Rotating the database password

1. Connect to the DB container and update the role:
   ```bash
   docker compose exec db psql -U postgres \
     -c "ALTER ROLE irrigai PASSWORD 'new-strong-password';"
   ```
2. Update `DATABASE_URL` and `DATABASE_URL_SYNC` in `.env.production` with the new password.
3. Restart:
   ```bash
   docker compose up -d --no-deps backend worker
   ```
4. Verify health: `curl -sf http://localhost:8000/health | jq .checks.db`

## Notes
- Never log secrets. Verify rotation by watching the health endpoint and application logs, not by echoing the value.
- After every rotation, update the secret in any backup/recovery documentation or CI/CD pipelines that use it.
