# Restore backup runbook

## When to use
- Database corruption or accidental data loss
- Restoring a specific point in time after a bad migration

## Backup location
Backups are written by the `backup` service defined in `docker-compose.yml` to the volume `irrigai_db_backups` (mounted at `/backups` inside the container). They follow the naming convention:
```
irrigai_YYYYMMDD_HHMMSS.sql.gz
```

## List available backups
```bash
docker run --rm \
  -v irrigai_db_backups:/backups \
  alpine ls -lh /backups
```

## Steps

### 1. Stop the application to prevent writes during restore
```bash
docker compose stop backend worker
```

### 2. Copy the desired backup out of the volume
```bash
docker run --rm \
  -v irrigai_db_backups:/backups \
  -v $(pwd):/out \
  alpine cp /backups/irrigai_20240115_030000.sql.gz /out/
```

### 3. Drop and recreate the database
```bash
docker compose exec db psql -U irrigai -c "DROP DATABASE irrigai;"
docker compose exec db psql -U irrigai -c "CREATE DATABASE irrigai OWNER irrigai;"
```

### 4. Restore
```bash
gunzip -c irrigai_20240115_030000.sql.gz | \
  docker compose exec -T db psql -U irrigai irrigai
```

### 5. Run any pending migrations
After restoring an older backup, the schema may be behind the current codebase:
```bash
docker compose run --rm backend alembic upgrade head
```

### 6. Restart the application
```bash
docker compose start backend worker
```

### 7. Verify
```bash
curl -sf http://localhost:8000/health | jq .
```

## Notes
- Backups are taken daily at 03:00 UTC. Point-in-time recovery within a day requires PostgreSQL WAL archiving (not currently configured).
- Test restores in a staging environment before performing them in production.
