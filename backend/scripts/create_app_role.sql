-- Create the restricted role the application connects as.
--
-- Row-level security is enforced against the *connecting role*. A superuser —
-- or the table owner without FORCE — ignores every policy, so running the
-- application as the database owner means RLS is enabled and doing nothing.
--
-- Migrations continue to run as the owner; only the application uses this role.
--
-- Usage (the password comes from the environment, never from this file):
--
--   psql "$DATABASE_ADMIN_URL" \
--     -v app_password="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')" \
--     -f scripts/create_app_role.sql
--
-- Then set DATABASE_URL to connect as avocado_app with that password, and keep
-- DATABASE_ADMIN_URL (the owner) for Alembic.

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'avocado_app') THEN
        CREATE ROLE avocado_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END $$;

ALTER ROLE avocado_app WITH PASSWORD :'app_password';

GRANT CONNECT ON DATABASE :"DBNAME" TO avocado_app;
GRANT USAGE ON SCHEMA public TO avocado_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO avocado_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO avocado_app;

-- Anything a later migration creates should be reachable too, without having
-- to re-run this script.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO avocado_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO avocado_app;

-- Deliberately NOT granted: CREATE on the schema, ownership of any table, and
-- any DDL right. The application reads and writes rows; it does not reshape
-- the database.
