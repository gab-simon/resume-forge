#!/bin/sh
# Creates the application role on the first start of an empty data directory.
# POSTGRES_USER owns the tables and runs the migrations; APP_DB_USER is the
# role of DB_URL, without SUPERUSER or BYPASSRLS, so PostgreSQL applies the
# row-level security policies to it.
set -eu

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set app_user="$APP_DB_USER" \
  --set app_password="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE SCHEMA IF NOT EXISTS resume_forge;
GRANT USAGE ON SCHEMA resume_forge TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA resume_forge
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA resume_forge
  GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
SQL
