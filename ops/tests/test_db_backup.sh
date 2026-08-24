#!/usr/bin/env bash
#
# Regression tests for ops/db-backup.sh.
#
# Each test drives run_cycle with stubbed postgres tools. The first three pin
# the defects behind the 2026-08-13 disk-full outage; the rest cover the paths
# that leak disk more slowly.
#
# Run: bash ops/tests/test_db_backup.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0

fail() { echo "  FAIL: $*"; FAIL=$((FAIL + 1)); }
pass() { PASS=$((PASS + 1)); }

assert_eq() {
  if [ "$1" = "$2" ]; then pass; else fail "$3 (expected '$2', got '$1')"; fi
}

assert_file_count() {
  local actual
  actual=$(find "$1" -maxdepth 1 -type f -name "$2" | wc -l | tr -d ' ')
  assert_eq "$actual" "$3" "$4"
}

# Build a sandbox: a BACKUP_DIR plus stub pg_dump/createdb/dropdb/psql on PATH.
setup() {
  WORK=$(mktemp -d)
  export BACKUP_DIR="$WORK/backups"
  export DROPPED_LOG="$WORK/dropped.log"
  mkdir -p "$BACKUP_DIR" "$WORK/bin"
  : >"$DROPPED_LOG"

  cat >"$WORK/bin/pg_dump" <<'STUB'
#!/usr/bin/env bash
if [ "${FAKE_PGDUMP_FAIL:-0}" = "1" ]; then
  echo 'pg_dump: error: could not translate host name "db" to address: Try again' >&2
  exit 1
fi
echo "-- fake dump"
echo "CREATE TABLE farm (id int);"
STUB

  cat >"$WORK/bin/createdb" <<'STUB'
#!/usr/bin/env bash
[ "${FAKE_CREATEDB_FAIL:-0}" = "1" ] && exit 1
exit 0
STUB

  cat >"$WORK/bin/dropdb" <<'STUB'
#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in --*) ;; *) echo "$arg" >>"$DROPPED_LOG" ;; esac
done
exit 0
STUB

  cat >"$WORK/bin/psql" <<'STUB'
#!/usr/bin/env bash
args="$*"
case "$args" in
  *pg_database*) printf '%s\n' ${FAKE_ORPHANS:-} ; exit 0 ;;
  *"COUNT(*) FROM farm"*) echo "${FAKE_FARM_COUNT:-7}" ; exit 0 ;;
  *) cat >/dev/null; [ "${FAKE_RESTORE_FAIL:-0}" = "1" ] && exit 1; exit 0 ;;
esac
STUB

  chmod +x "$WORK/bin"/*
  export PATH="$WORK/bin:$PATH"

  export BACKUP_MIN_FREE_MB=0
  export BACKUP_KEEP_MIN=3
  export BACKUP_RETENTION_DAYS=7
  unset FAKE_PGDUMP_FAIL FAKE_CREATEDB_FAIL FAKE_RESTORE_FAIL FAKE_ORPHANS
  export FAKE_FARM_COUNT=7

  DB_BACKUP_LIB=1 . "$SCRIPT_DIR/db-backup.sh"
}

teardown() { rm -rf "$WORK"; }

# Nine backups, all older than the retention window, to prove pruning behaviour.
seed_old_backups() {
  local i
  for i in $(seq 1 "${1:-9}"); do
    echo "old" | gzip >"$BACKUP_DIR/irrigai_2026070${i}_000000.sql.gz"
    touch -d "$((20 + i)) days ago" "$BACKUP_DIR/irrigai_2026070${i}_000000.sql.gz"
  done
}

# ── The outage ────────────────────────────────────────────────────────────────

echo "a failed pg_dump is not reported as a backup"
setup
  seed_old_backups 3
  FAKE_PGDUMP_FAIL=1 run_cycle >"$WORK/out" 2>&1
  assert_eq "$?" "1" "run_cycle must report failure when pg_dump fails"
  # The original bug: gzip succeeded on empty input, so a 20-byte file appeared
  # alongside the 3 seeded ones and the log claimed "Backup written".
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 3 "no new archive may be created"
  assert_file_count "$BACKUP_DIR" '*.part' 0 "the partial file must be discarded"
teardown

echo "a failed cycle does not purge existing backups"
setup
  seed_old_backups 9
  FAKE_PGDUMP_FAIL=1 run_cycle >/dev/null 2>&1
  # Retention must not run off the back of a failure — but equally, the failure
  # must not skip it the way the && chain did. Old backups survive because the
  # cycle bailed before prune, not because prune was unreachable.
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 9 "backups must survive a failed dump"
teardown

echo "low disk skips the dump but still prunes"
setup
  seed_old_backups 9
  # MIN_FREE_MB is resolved once at startup, so override the resolved value.
  MIN_FREE_MB=999999999 run_cycle >/dev/null 2>&1
  assert_eq "$?" "1" "run_cycle must fail when free space is below the floor"
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 3 "prune must run when disk is low, down to keep-min"
teardown

# ── Normal operation ──────────────────────────────────────────────────────────

echo "a good cycle writes, verifies and prunes"
setup
  seed_old_backups 9
  run_cycle >"$WORK/out" 2>&1
  assert_eq "$?" "0" "a healthy cycle must succeed"
  # 9 seeded + 1 new = 10, pruned oldest-first back down to keep-min.
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 3 "retention must leave exactly keep-min backups"
  assert_file_count "$BACKUP_DIR" '*.part' 0 "no partial file may survive a successful cycle"
teardown

echo "retention never drops below keep-min"
setup
  seed_old_backups 2
  run_cycle >/dev/null 2>&1
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 3 "two stale backups plus one new must all survive"
teardown

# ── Verification-database leaks ───────────────────────────────────────────────

echo "the verification database is dropped when the restore fails"
setup
  FAKE_RESTORE_FAIL=1 run_cycle >/dev/null 2>&1
  assert_eq "$?" "1" "a failed restore must fail the cycle"
  assert_eq "$(grep -c irrigai_verify_ "$DROPPED_LOG")" "1" "the verify database must be dropped anyway"
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 0 "an unverified archive must not be kept"
teardown

echo "the verification database is dropped after a successful restore"
setup
  run_cycle >/dev/null 2>&1
  assert_eq "$(grep -c irrigai_verify_ "$DROPPED_LOG")" "1" "the verify database must not outlive the check"
teardown

echo "orphaned verification databases are swept at the start of a cycle"
setup
  FAKE_ORPHANS="irrigai_verify_20260810_1 irrigai_verify_20260811_2" run_cycle >/dev/null 2>&1
  assert_eq "$(grep -c 'irrigai_verify_2026081' "$DROPPED_LOG")" "2" "both orphans must be dropped"
teardown

echo "an empty dump fails verification rather than becoming a backup"
setup
  FAKE_FARM_COUNT=0 run_cycle >/dev/null 2>&1
  assert_eq "$?" "1" "a dump restoring zero farms must not be accepted"
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 0 "an empty dump must not be kept"
teardown

echo
echo "passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ]
