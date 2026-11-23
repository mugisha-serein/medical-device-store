# R1: Secret handling and repository hygiene

The public repository previously tracked backend/.env, a local Python environment, compiled caches and logs. Stopping tracking in a new revision does not remove exposure from previous commits.

## Setup
Copy the root .env.example to root .env for Docker Compose. SQLite requires no database password. Use matching async/sync SQLite URLs and a unique JWT_SECRET_KEY of at least 32 characters. Protect the database file and its backups with operating-system permissions. Copy backend/.env.example to backend/.env for local backend development, with private values. Never commit actual credentials.

Run docker compose config to check the configuration. Supply ADMIN_SEED_PASSWORD (unique, minimum 12 characters) only when initially seeding the administrator. Existing Compose configuration is development-oriented, using bind mounts and reload; do not treat it as a production setup.

## Secret incident review
Inspect Git history and deployment settings without printing values. Rotate any previously active database, JWT, payment, webhook, email, or administrator credentials. Rotating the JWT key invalidates signed sessions. Coordinate external secret storage and deployments. History rewriting is excluded from R1 and needs separate approval.

## Verify
Install requirements-test.txt, copy .env.test.example to .env.test, and run pytest from backend and npm run check from repository root. Check git ls-files backend/.env backend/env backend/celery_output.log (must be empty), git check-ignore backend/.env, docker compose config, and startup with unset/placeholder JWT_SECRET_KEY (must fail). Never assert a check passed unless executed.

## SQLite operational safeguards
Tests require the explicit in-memory test URL, reject a previously initialized file engine, and verify connection identity before destructive fixtures. Startup requires the existing application file at the expected Alembic revision. Initialization never replaces an existing file; creation is explicit. See README.md for tested SQLite online backup and restore commands. Keep database files, backups and live journal/WAL/SHM files protected with operating-system permissions. Do not manually remove live sidecars. SQL bound parameters and Pydantic validation inputs are hidden in errors. No PostgreSQL credential, database, backup or volume was modified during the SQLite cutover.
