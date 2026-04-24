# Rollback runbook

Use this when a deploy causes regressions and must be reverted.

## Decision criteria
Roll back if, within 15 minutes of deploy:
- Health endpoint returns `"degraded"` and cannot be fixed with a config change
- 5xx rate > 5% sustained for more than 2 minutes (see Prometheus `High5xxRate` alert)
- Critical user-facing feature is broken and cannot be hot-patched

## Steps

### 1. Identify the previous working commit
```bash
git log --oneline -10
```
Note the commit SHA immediately before the broken deploy.

### 2. Check out the previous version
```bash
git checkout <previous-sha>
```

### 3. Rebuild images from the previous commit
```bash
docker compose build backend frontend
```

### 4. Assess whether a migration downgrade is needed
```bash
docker compose run --rm backend alembic history --verbose | head -20
```
If the new deploy added migrations and the schema change is not backward-compatible, run:
```bash
docker compose run --rm backend alembic downgrade <previous-revision-id>
```
**Only downgrade if the new column/table would cause errors with the old code.** Additive migrations (new nullable columns, new tables) are usually safe to leave in place.

### 5. Restart services
```bash
docker compose up -d --no-deps backend worker frontend
```

### 6. Verify health
```bash
curl -sf http://localhost:8000/health | jq .
```

### 7. Re-checkout main for future work
```bash
git checkout main
```
Fix the regression in a new commit on main; do not push the broken commit.

## Notes
- Never force-push main. Fix forward or revert via `git revert`.
- If a migration downgrade is complex or risky, consider keeping the new schema and deploying a patched version of the code instead.
