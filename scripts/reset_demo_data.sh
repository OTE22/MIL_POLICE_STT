#!/usr/bin/env bash
# =============================================================================
#  Clear operational data from a development / demo / test deployment.
# =============================================================================
#  Removes sessions, recordings, transcripts, speakers, subjects, voice prints,
#  canonical identities, workstations and the audit log - from the database AND
#  from disk, so no orphaned evidence files are left behind.
#
#  KEPT: users, investigator profiles, roles, permissions, role mappings, the
#  Alembic version, secrets/ and the model weights.
#
#      ./reset_demo_data.sh --yes
#
#  --yes alone is not enough: the script refuses to run unless the environment
#  is explicitly development, demo or test.
# =============================================================================
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIRMED="false"

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[34m'; DIM=$'\033[2m'; RST=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$BLU" "$*" "$RST"; }
ok()   { printf '  %s[ ok ]%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '  %s[warn]%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '\n%s[REFUSED]%s %s\n\n' "$RED" "$RST" "$*" >&2; exit 1; }
note() { printf '  %s%s%s\n' "$DIM" "$*" "$RST"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) CONFIRMED="true"; shift ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

# =============================================================================
step "Safety checks"
# =============================================================================
[ "$CONFIRMED" = "true" ] || die "refusing to run without --yes"

[ -f "$ROOT/.env" ] || die "no .env at $ROOT - cannot determine the environment"
# shellcheck disable=SC1091
set -a; . "$ROOT/.env"; set +a

ENVIRONMENT="${CENTRAL_ENVIRONMENT:-}"
case "$ENVIRONMENT" in
  development|demo|test)
    ok "environment is '$ENVIRONMENT'"
    ;;
  production|prod|staging)
    die "CENTRAL_ENVIRONMENT is '$ENVIRONMENT'. This script never touches that."
    ;;
  "")
    die "CENTRAL_ENVIRONMENT is not set. Refusing to guess."
    ;;
  *)
    die "CENTRAL_ENVIRONMENT is '$ENVIRONMENT', which is not development, demo or test."
    ;;
esac

DB_NAME="${POSTGRES_DB:-}"
DB_USER="${POSTGRES_USER:-}"
[ -n "$DB_NAME" ] && [ -n "$DB_USER" ] || die "POSTGRES_DB / POSTGRES_USER are not set"
case "$DB_NAME" in
  *prod*) die "database name '$DB_NAME' looks like production" ;;
esac
ok "database '$DB_NAME'"

# Resolve the storage root canonically before deleting anything inside it. Never rm -rf a
# path that has not been proven to sit where it is supposed to.
STORAGE_ROOT="$(cd "$ROOT/storage" 2>/dev/null && pwd -P)" \
  || die "storage directory not found at $ROOT/storage"
case "$STORAGE_ROOT" in
  "$ROOT"/*) ;;
  *) die "storage root '$STORAGE_ROOT' resolves outside the project - refusing to delete" ;;
esac
[ "$STORAGE_ROOT" != "/" ] || die "storage root resolved to /"
ok "storage root $STORAGE_ROOT"

docker compose -f "$ROOT/docker-compose.yml" ps postgres >/dev/null 2>&1 \
  || die "docker compose is not available in $ROOT"

printf '\n  %sThis deletes all sessions, recordings, transcripts, voice prints and the audit log.%s\n' "$YEL" "$RST"
printf '  Users and roles are kept. Environment: %s, database: %s\n' "$ENVIRONMENT" "$DB_NAME"
if [ -t 0 ]; then
  printf '  Type the database name to confirm: '
  read -r typed
  [ "$typed" = "$DB_NAME" ] || die "confirmation did not match"
fi

# =============================================================================
step "Clearing the database"
# =============================================================================
# person_identities is deleted, NOT truncated. TRUNCATE ... CASCADE clears every table holding
# a foreign key into the named ones - and since investigator_profiles gained identity_id
# (b2e94c1f7a06) that now silently includes the staff profiles this script promises to KEEP.
# DELETE respects the declared ON DELETE SET NULL instead, so a profile survives and simply
# loses its identity link. person_identifiers is covered by its own ON DELETE CASCADE.
docker compose -f "$ROOT/docker-compose.yml" exec -T postgres   psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" -c "
UPDATE investigator_profiles SET identity_id = NULL;
DELETE FROM person_identities;" >/dev/null
ok "canonical identities cleared (staff profiles kept, identity links dropped)"

# CASCADE handles the FK order; RESTART IDENTITY resets sequences.
docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" -c "
TRUNCATE TABLE
  audit_logs,
  transcript_segments,
  transcripts,
  session_speakers,
  voice_enrollments,
  subject_documents,
  subjects,
  local_processing_jobs,
  audio_recordings,
  session_investigators,
  investigation_sessions,
  workstations
RESTART IDENTITY CASCADE;" >/dev/null
ok "operational tables truncated"

remaining="$(docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
  psql -tAX -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT coalesce(sum(n),0) FROM (
    SELECT count(*) AS n FROM investigation_sessions
    UNION ALL SELECT count(*) FROM voice_enrollments
    UNION ALL SELECT count(*) FROM person_identities
    UNION ALL SELECT count(*) FROM session_speakers
    UNION ALL SELECT count(*) FROM audit_logs) s;" | tr -d '\r')"
[ "$remaining" = "0" ] || die "expected empty operational tables, found $remaining rows"
ok "verified empty"

kept="$(docker compose -f "$ROOT/docker-compose.yml" exec -T postgres \
  psql -tAX -U "$DB_USER" -d "$DB_NAME" -c "SELECT count(*) FROM users;" | tr -d '\r')"
ok "$kept user account(s) preserved"

# =============================================================================
step "Clearing stored files"
# =============================================================================
for sub in recordings subject-documents; do
  target="$STORAGE_ROOT/$sub"
  if [ -d "$target" ]; then
    # Delete the CONTENTS, not the directory: the backend expects it to exist.
    find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    ok "$sub cleared"
  else
    note "$sub does not exist - nothing to clear"
  fi
done

files="$(find "$STORAGE_ROOT" -type f 2>/dev/null | wc -l | tr -d ' ')"
[ "$files" = "0" ] || warn "$files file(s) remain under $STORAGE_ROOT"

cat <<EOF

$(printf '%s' "$GRN")Demo data cleared.$(printf '%s' "$RST")

  Kept: users, roles, permissions, investigator profiles, Alembic state,
        secrets/ and the model weights.

  Both tabs of بصمات الأصوات will be empty until a recording is processed and a
  speaker is identified.
EOF
