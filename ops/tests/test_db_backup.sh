#!/usr/bin/env bash
#
# Regression tests for ops/db-backup.sh.
#
# Each test drives run_cycle with stubbed postgres tools. The first three pin
# the defects behind the 2026-08-13 disk-full outage; the rest cover two-tier
# verification and the ordering that keeps the full restore from running on a
# disk retention has not yet relieved.
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
  export CREATEDB_LOG="$WORK/createdb.log"
  export CREATEDB_SAW_COUNT="$WORK/createdb_saw_count"
  mkdir -p "$BACKUP_DIR" "$WORK/bin"
  : >"$DROPPED_LOG"
  : >"$CREATEDB_LOG"
  : >"$CREATEDB_SAW_COUNT"

  # Emits pg_dump's real completion trailer unless asked to truncate. Modern
  # pg_dump ends with \unrestrict *after* the completion comment, so the check
  # has to look at the last few lines, not only the final one.
  cat >"$WORK/bin/pg_dump" <<'STUB'
#!/usr/bin/env bash
if [ "${FAKE_PGDUMP_FAIL:-0}" = "1" ]; then
  echo 'pg_dump: error: could not translate host name "db" to address: Try again' >&2
  exit 1
fi
echo "-- fake dump"
echo "CREATE TABLE farm (id int);"
if [ "${FAKE_DUMP_TRUNCATED:-0}" != "1" ]; then
  printf -- '--\n-- PostgreSQL database dump complete\n--\n\n'
  echo '\unrestrict FAKETOKEN'
fi
STUB

  # Records how many backups existed when it ran, which is how the ordering
  # test proves prune happened first.
  cat >"$WORK/bin/createdb" <<'STUB'
#!/usr/bin/env bash
[ "${FAKE_CREATEDB_FAIL:-0}" = "1" ] && exit 1
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'irrigai_*.sql.gz' | wc -l | tr -d ' ' >"$CREATEDB_SAW_COUNT"
echo "$*" >>"$CREATEDB_LOG"
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
  export BACKUP_FULL_VERIFY_INTERVAL_DAYS=7
  export BACKUP_FULL_VERIFY_MIN_FREE_MB=0
  unset FAKE_PGDUMP_FAIL FAKE_CREATEDB_FAIL FAKE_RESTORE_FAIL FAKE_ORPHANS FAKE_DUMP_TRUNCATED
  export FAKE_FARM_COUNT=7

  DB_BACKUP_LIB=1 . "$SCRIPT_DIR/db-backup.sh"
}

teardown() { rm -rf "$WORK"; }

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

# ── Cheap integrity check (every cycle) ───────────────────────────────────────

echo "a dump without the completion trailer is discarded"
setup
  seed_old_backups 3
  # A valid gzip wrapping partial SQL — exactly how the Aug 10-12 dumps looked.
  FAKE_DUMP_TRUNCATED=1 run_cycle >/dev/null 2>&1
  assert_eq "$?" "1" "a dump missing the completion marker must fail"
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 3 "a truncated dump must not become a backup"
  assert_file_count "$BACKUP_DIR" '*.part' 0 "the partial file must be discarded"
teardown

echo "a corrupt archive is rejected by the integrity check"
setup
  printf '\x1f\x8b\x08\x00 truncated garbage' >"$BACKUP_DIR/broken.sql.gz"
  verify_archive_integrity "$BACKUP_DIR/broken.sql.gz" >/dev/null 2>&1
  assert_eq "$?" "1" "a corrupt gzip must fail the integrity check"
teardown

echo "the integrity check accepts a complete dump"
setup
  pg_dump | gzip >"$BACKUP_DIR/good.sql.gz"
  verify_archive_integrity "$BACKUP_DIR/good.sql.gz" >/dev/null 2>&1
  assert_eq "$?" "0" "a complete dump must pass the integrity check"
teardown

# ── Normal operation ──────────────────────────────────────────────────────────

echo "a good cycle writes, verifies and prunes"
setup
  seed_old_backups 9
  run_cycle >"$WORK/out" 2>&1
  assert_eq "$?" "0" "a healthy cycle must succeed"
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 3 "retention must leave exactly keep-min backups"
  assert_file_count "$BACKUP_DIR" '*.part' 0 "no partial file may survive a successful cycle"
teardown

echo "retention never drops below keep-min"
setup
  seed_old_backups 2
  run_cycle >/dev/null 2>&1
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 3 "two stale backups plus one new must all survive"
teardown

# ── Ordering: prune must precede the full restore ─────────────────────────────

echo "retention runs before the full restore, not after"
setup
  seed_old_backups 9
  run_cycle >/dev/null 2>&1
  # The restore needs ~20GB of transient disk. If prune ran after it (the
  # original ordering), createdb would have seen all 10 archives still present.
  assert_eq "$(cat "$CREATEDB_SAW_COUNT")" "3" "prune must have run before the restore began"
teardown

# ── Full restore scheduling ───────────────────────────────────────────────────

echo "the full restore runs when no marker exists"
setup
  run_cycle >/dev/null 2>&1
  assert_eq "$(wc -l <"$CREATEDB_LOG" | tr -d ' ')" "1" "a first run must perform the full restore"
  [ -f "$BACKUP_DIR/.last_full_verify" ] && pass || fail "the marker must be written on success"
teardown

echo "the full restore is skipped while the marker is fresh"
setup
  touch "$BACKUP_DIR/.last_full_verify"
  run_cycle >/dev/null 2>&1
  assert_eq "$?" "0" "a cycle that skips the full restore still succeeds"
  assert_eq "$(wc -l <"$CREATEDB_LOG" | tr -d ' ')" "0" "no restore may run inside the interval"
teardown

echo "the full restore runs again once the marker is stale"
setup
  touch -d "8 days ago" "$BACKUP_DIR/.last_full_verify"
  run_cycle >/dev/null 2>&1
  assert_eq "$(wc -l <"$CREATEDB_LOG" | tr -d ' ')" "1" "a stale marker must trigger the full restore"
teardown

echo "the full restore is skipped when disk is tight, without failing the cycle"
setup
  FULL_VERIFY_MIN_FREE_MB=999999999 run_cycle >/dev/null 2>&1
  assert_eq "$?" "0" "skipping the restore on low disk is not a failure"
  assert_eq "$(wc -l <"$CREATEDB_LOG" | tr -d ' ')" "0" "no restore may run without headroom"
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 1 "the backup is kept — it passed integrity"
teardown

# ── Full restore failure ──────────────────────────────────────────────────────

echo "a failed full restore keeps the archive but fails the cycle"
setup
  FAKE_RESTORE_FAIL=1 run_cycle >/dev/null 2>&1
  assert_eq "$?" "1" "a failed restore must fail the cycle"
  # It passed integrity, so it is a complete dump. Deleting the newest backup
  # because the restore environment misbehaved is worse than keeping it flagged.
  assert_file_count "$BACKUP_DIR" 'irrigai_*.sql.gz' 1 "the archive must be kept"
  [ -f "$BACKUP_DIR/.last_full_verify" ] && fail "the marker must not be written on failure" || pass
teardown

echo "a restore yielding zero farms fails the cycle"
setup
  FAKE_FARM_COUNT=0 run_cycle >/dev/null 2>&1
  assert_eq "$?" "1" "a restore with no farms must not count as verified"
teardown

# ── Verification-database leaks ───────────────────────────────────────────────

echo "the verification database is dropped when the restore fails"
setup
  FAKE_RESTORE_FAIL=1 run_cycle >/dev/null 2>&1
  assert_eq "$(grep -c irrigai_verify_ "$DROPPED_LOG")" "1" "the verify database must be dropped anyway"
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

echo
echo "passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ]
