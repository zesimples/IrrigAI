# Restore backup runbook

## When to use
- Database corruption or accidental data loss
- Restoring a specific point in time after a bad migration

## Backup location
Backups are written by the `db-backup` service defined in `docker-compose.yml` to
the host directory `./backups` (mounted at `/backups` inside the container). They
follow the naming convention:
```
irrigai_YYYYMMDD_HHMMSS.sql.gz
```

## List available backups
```bash
ls -lh ./backups
```

## Steps

### 1. Stop the application to prevent writes during restore
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop backend worker frontend
```

### 2. Select and preserve the desired backup
```bash
cp ./backups/irrigai_20240115_030000.sql.gz /tmp/irrigai-restore.sql.gz
```

### 3. Drop and recreate the database
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  psql -U irrigai -d postgres -c "DROP DATABASE irrigai WITH (FORCE);"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  psql -U irrigai -d postgres -c "CREATE DATABASE irrigai OWNER irrigai;"
```

### 4. Restore
```bash
gunzip -c /tmp/irrigai-restore.sql.gz | \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  psql -v ON_ERROR_STOP=1 -U irrigai irrigai
```

### 5. Run any pending migrations
After restoring an older backup, the schema may be behind the current codebase:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head
```

### 6. Restart the application
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml start backend worker frontend
```

### 7. Verify
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend \
  python -c "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8000/health')), indent=2))"
curl -sf https://YOUR_DOMAIN/health | jq .
```

## Notes
- Backups are taken daily at 03:00 UTC. Point-in-time recovery within a day requires PostgreSQL WAL archiving (not currently configured).
- Test restores in a staging environment before performing them in production.
