#!/usr/bin/env bash
#
# Periodic pg_dump with verification and retention.
#
# This replaces an inline `&&`-chained entrypoint that took production down on
# 2026-08-13. Three defects in that chain, all reproduced in ops/tests:
#
#   1. `pg_dump | gzip > "$FILE"` reports the exit status of *gzip*, which
#      succeeds on empty input. A failed dump wrote a valid 20-byte archive and
#      logged "Backup written".
#   2. Retention (`find -mtime +7 -delete`) sat downstream of the failure, so
#      the one step that frees disk stopped running exactly when it was needed.
#   3. `sleep 86400` also sat downstream, so a failing cycle span with no delay
#      — one dump file every ~15s until the disk hit 100%.
#
# The rules that keep those from recurring: every cycle sleeps, no matter how it
# ends; a dump is only named like a backup once it is complete and intact; and
# retention never drops below BACKUP_KEEP_MIN surviving backups.
#
# Verification is two-tier, because proving a dump restores costs a full copy of
# the database (~20GB on prod as of 2026-08-24) and ~45 minutes:
#
#   * Every cycle: decompress the archive and require pg_dump's completion
#     trailer. One pass, no disk. This alone catches every bad dump the
#     2026-08-13 outage produced.
#   * Every BACKUP_FULL_VERIFY_INTERVAL_DAYS: also restore into a throwaway
#     database and count farms. Skipped when disk is tight — the cheap check
#     already passed, so a skip is not a failure.
#
# Ordering matters: prune runs after the archive is named but *before* the full
# restore, so retention frees space at the moment the restore needs it.

set -uo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
KEEP_MIN="${BACKUP_KEEP_MIN:-3}"
MIN_FREE_MB="${BACKUP_MIN_FREE_MB:-20480}"
FULL_VERIFY_INTERVAL_DAYS="${BACKUP_FULL_VERIFY_INTERVAL_DAYS:-7}"
FULL_VERIFY_MIN_FREE_MB="${BACKUP_FULL_VERIFY_MIN_FREE_MB:-30720}"

# Touched only after a full restore succeeds. Lives in BACKUP_DIR so it survives
# container recreates.
FULL_VERIFY_MARKER="${BACKUP_DIR}/.last_full_verify"

log() { echo "[db-backup] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

free_mb() { df -Pm "$BACKUP_DIR" | awk 'NR==2 {print $4}'; }

backup_count() {
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'irrigai_*.sql.gz' 2>/dev/null | wc -l
}

# Drop verification databases orphaned by an interrupted cycle. Each one is a
# full copy of the database living inside the postgres volume, so a leak here
# consumes disk far faster than the dumps do.
drop_orphan_verify_dbs() {
  local orphans db
  orphans=$(psql -tAc \
    "SELECT datname FROM pg_database WHERE datname LIKE 'irrigai_verify_%'" 2>/dev/null) || return 0
  while read -r db; do
    [ -n "$db" ] || continue
    log "dropping orphaned verification database ${db}"
    dropdb --if-exists "$db" >/dev/null 2>&1 || log "WARN: could not drop ${db}"
  done <<<"$orphans"
}

# Cheap integrity check: one decompression pass, no disk cost.
#
# `gunzip -t` alone is not enough. If pg_dump dies mid-stream, gzip sees a clean
# EOF and finalises a *valid* archive wrapping partial SQL — that is how the
# 2026-08-13 dumps looked intact at the container level. Requiring the trailer
# pg_dump writes last is what actually proves the dump finished. Modern pg_dump
# emits `\unrestrict <token>` after the completion comment, so check the last
# few lines rather than only the final one.
verify_archive_integrity() {
  local archive="$1" trailer rc
  trailer=$(set -o pipefail; gunzip -c "$archive" 2>/dev/null | tail -5)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    log "ERROR: ${archive} is truncated or corrupt (gunzip exit ${rc})"
    return 1
  fi
  case "$trailer" in
    *"PostgreSQL database dump complete"*) return 0 ;;
    *)
      log "ERROR: ${archive} has no completion marker — pg_dump did not finish"
      return 1
      ;;
  esac
}

# Expensive check: restore the archive into a throwaway database and confirm it
# holds real rows.
restore_into() {
  local archive="$1" verify_db="$2" farms
  gunzip -c "$archive" | psql -q "$verify_db" >/dev/null 2>&1 || return 1
  farms=$(psql -tA -c 'SELECT COUNT(*) FROM farm;' "$verify_db" 2>/dev/null) || return 1
  [ -n "$farms" ] && [ "$farms" -gt 0 ] 2>/dev/null || return 1
  log "full restore verified ${archive} (farm_count=${farms})"
}

full_verify_due() {
  local now last age
  [ -f "$FULL_VERIFY_MARKER" ] || return 0
  now=$(date +%s)
  last=$(stat -c %Y "$FULL_VERIFY_MARKER" 2>/dev/null || echo 0)
  age=$(( (now - last) / 86400 ))
  [ "$age" -ge "$FULL_VERIFY_INTERVAL_DAYS" ]
}

# Returns non-zero only when a restore was attempted and failed. A skip — not
# due, or not enough disk — is a success: the archive already passed the
# integrity check that runs every cycle.
maybe_full_verify() {
  local archive="$1" verify_db avail rc
  if ! full_verify_due; then
    log "full restore not due (runs every ${FULL_VERIFY_INTERVAL_DAYS}d)"
    return 0
  fi

  avail=$(free_mb)
  if [ "$avail" -lt "$FULL_VERIFY_MIN_FREE_MB" ]; then
    log "WARN: full restore due but only ${avail}MB free (need ${FULL_VERIFY_MIN_FREE_MB}MB) — skipping"
    return 0
  fi

  verify_db="irrigai_verify_$(date +%Y%m%d_%H%M%S)"
  if ! createdb "$verify_db" >/dev/null 2>&1; then
    log "ERROR: could not create verification database ${verify_db}"
    return 1
  fi

  restore_into "$archive" "$verify_db"
  rc=$?
  # Unconditional: the verify database must not outlive the check that made it.
  dropdb --if-exists "$verify_db" >/dev/null 2>&1 || log "WARN: could not drop ${verify_db}"

  if [ "$rc" -ne 0 ]; then
    # Deliberately kept. It passed integrity, so it is a complete dump; a failed
    # restore here more likely means a broken restore environment than a bad
    # archive, and deleting the newest backup on that evidence is worse than
    # keeping it flagged.
    log "ERROR: full restore FAILED for ${archive} — archive KEPT (it passed integrity checks)"
    return 1
  fi

  touch "$FULL_VERIFY_MARKER"
}

# Delete backups older than RETENTION_DAYS, oldest first, never going below
# KEEP_MIN. Deliberately callable even when a cycle failed: pruning is how the
# disk recovers, so it must not be gated on a successful dump.
prune() {
  local count deletable
  count=$(backup_count)
  deletable=$(( count - KEEP_MIN ))
  if [ "$deletable" -le 0 ]; then
    log "retention: ${count} backup(s) present, keep-min ${KEEP_MIN} — nothing pruned"
  else
    # busybox find (this image is Alpine) has no -printf, so age-sort via stat.
    find "$BACKUP_DIR" -maxdepth 1 -type f -name 'irrigai_*.sql.gz' \
      -mtime "+${RETENTION_DAYS}" -exec stat -c '%Y %n' {} + 2>/dev/null \
      | sort -n | head -n "$deletable" | cut -d' ' -f2- \
      | while read -r stale; do
          log "retention: removing ${stale}"
          rm -f "$stale"
        done
  fi
  # Partial dumps from an interrupted cycle are never backups. Clear the ones
  # too old to belong to a run in flight.
  find "$BACKUP_DIR" -maxdepth 1 -type f -name 'irrigai_*.sql.gz.part' \
    -mmin +120 -delete 2>/dev/null || true
}

run_cycle() {
  local avail stamp final part rc

  avail=$(free_mb) || { log "ERROR: cannot stat ${BACKUP_DIR}"; return 1; }
  if [ "$avail" -lt "$MIN_FREE_MB" ]; then
    log "ERROR: ${avail}MB free in ${BACKUP_DIR}, need ${MIN_FREE_MB}MB — skipping dump"
    prune
    return 1
  fi

  drop_orphan_verify_dbs

  stamp=$(date +%Y%m%d_%H%M%S)
  final="${BACKUP_DIR}/irrigai_${stamp}.sql.gz"
  part="${final}.part"
  rm -f "$part"

  # pipefail is what stops gzip's success from masking a pg_dump failure.
  ( set -o pipefail; pg_dump | gzip > "$part" )
  rc=$?
  if [ "$rc" -ne 0 ]; then
    log "ERROR: pg_dump failed (exit ${rc}) — discarding ${part}"
    rm -f "$part"
    return 1
  fi

  if ! verify_archive_integrity "$part"; then
    log "ERROR: discarding ${part}"
    rm -f "$part"
    return 1
  fi

  # A complete, intact archive earns a backup's name.
  mv "$part" "$final"
  log "backup written: ${final} ($(du -h "$final" | cut -f1))"

  # Before the full restore, not after: the restore needs ~20GB of transient
  # disk, and retention is what frees it.
  prune

  maybe_full_verify "$final"
}

main() {
  mkdir -p "$BACKUP_DIR"
  log "starting: interval=${INTERVAL_SECONDS}s retention=${RETENTION_DAYS}d keep-min=${KEEP_MIN} min-free=${MIN_FREE_MB}MB full-verify=${FULL_VERIFY_INTERVAL_DAYS}d"
  while true; do
    run_cycle || log "cycle failed — retrying in ${INTERVAL_SECONDS}s"
    sleep "$INTERVAL_SECONDS"
  done
}

# Sourcing with DB_BACKUP_LIB=1 exposes the functions without entering the loop,
# which is how ops/tests/test_db_backup.sh drives the failure paths.
if [ "${DB_BACKUP_LIB:-0}" != "1" ]; then
  main "$@"
fi
