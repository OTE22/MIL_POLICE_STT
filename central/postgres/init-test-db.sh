#!/bin/sh
# Creates an isolated database for the automated test-suite on first start.
# Production deployments set CREATE_TEST_DB=false so the cluster holds only the
# operational database.
set -e
if [ "${CREATE_TEST_DB:-true}" != "true" ]; then
  echo "CREATE_TEST_DB=${CREATE_TEST_DB} - skipping the test database"
  exit 0
fi
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE "${POSTGRES_DB}_test" OWNER "$POSTGRES_USER";
EOSQL
