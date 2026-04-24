# Provider outage runbook

## Affected providers and their impact

| Provider | Env vars | Impact when down |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | AI chat and LLM explanations fail; agronomic recommendations still generated (no explanation text) |
| IrriWatch / Hydrosat | `IRRIWATCH_*` | Probe readings and weather data not ingested; recommendations use stale data |
| MyIrrigation | `MYIRRIGATION_*` | Same as IrriWatch |
| Redis | `REDIS_URL` | Rate limiting and job locks fail; backend degrades gracefully but may allow duplicate jobs |
| PostgreSQL | `DATABASE_URL` | Full service outage |

## Diagnosing an outage

1. Check the health endpoint first:
   ```bash
   curl -sf http://localhost:8000/health | jq .
   ```
2. Check Prometheus for elevated `irrigai_scheduler_job_runs_total{status="failure"}` or `irrigai_ai_requests_total{status="failure"}`.
3. Check backend logs for the affected component:
   ```bash
   docker compose logs --tail=100 backend | grep '"lvl":"ERROR"'
   ```

## Response by provider

### OpenAI outage
- The LLM is used only for explanations and chat. The agronomic engine runs independently.
- Recommendations continue to be generated; only the natural-language explanation is missing.
- No action required — the system degrades gracefully. Monitor `irrigai_ai_requests_total{status="failure"}` in Prometheus.
- When OpenAI recovers, requests will succeed automatically.

### Probe / Weather provider outage (IrriWatch or MyIrrigation)
- Data ingestion jobs will log errors and increment `scheduler_job_runs_total{job="data_ingestion", status="failure"}`.
- Recommendations will be based on the last ingested data. The UI shows `data_freshness_hours` in the sector card — users can see data is stale.
- If the outage lasts more than 6 hours, consider notifying users.
- Switch to mock provider temporarily for testing only:
  ```bash
  # In .env.production — NEVER do this in production with real users without clear communication
  PROBE_PROVIDER=mock
  WEATHER_PROVIDER=mock
  ```
- When the provider recovers, the next ingestion job will catch up with `lookback_hours=4` by default.

### Redis outage
- Rate limiting is disabled (slowapi fails open).
- Job locks cannot be acquired — scheduler jobs will still run but may run more than once during recovery.
- The health endpoint will show `"redis": "error"` and return HTTP 503.
- Restart Redis container:
  ```bash
  docker compose restart redis
  ```
- Verify: `curl -sf http://localhost:8000/health | jq .checks.redis`

### Database outage
- Complete service outage. All API endpoints return 503.
- Diagnose:
  ```bash
  docker compose logs db --tail=50
  docker compose exec db pg_isready -U irrigai
  ```
- Restart if the container exited unexpectedly:
  ```bash
  docker compose up -d db
  ```
- If data is lost, follow the `restore-backup.md` runbook.

## Escalation
If a provider outage exceeds 4 hours and affects data integrity, escalate by:
1. Notifying affected farm owners (manual email for now — no automated notification system yet).
2. Documenting the incident with start time, affected farms, and data gap in the team channel.
