# R1: Secret handling and repository hygiene

The public repository previously tracked backend/.env, a local Python environment, compiled caches and logs. Stopping tracking in a new revision does not remove exposure from previous commits.

## Setup
Copy the root .env.example to root .env for Docker Compose. Provide a strong unique POSTGRES_PASSWORD, DATABASE_URL and DATABASE_URL_SYNC (using hostname postgres), and a unique JWT_SECRET_KEY of at least 32 characters. Percent-encode URL-reserved password characters in connection URLs. Copy backend/.env.example to backend/.env for local backend development, with private values. Never commit actual credentials.

Run docker compose config to check the configuration. Supply ADMIN_SEED_PASSWORD (unique, minimum 12 characters) only when initially seeding the administrator. Existing Compose configuration is development-oriented, using bind mounts and reload; do not treat it as a production setup.

## Secret incident review
Inspect Git history and deployment settings without printing values. Rotate any previously active database, JWT, payment, webhook, email, or administrator credentials. Rotating the JWT key invalidates signed sessions. Coordinate external secret storage and deployments. History rewriting is excluded from R1 and needs separate approval.

## Verify
Run pytest from backend and npm run check from repository root. Check git ls-files backend/.env backend/env backend/celery_output.log (must be empty), git check-ignore backend/.env, docker compose config, and startup with unset/placeholder JWT_SECRET_KEY (must fail). Never assert a check passed unless executed.
