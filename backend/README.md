# Active Life Medical Backend API

FastAPI backend for the Active Life Medical medical devices e-commerce platform. This API replaces the demo frontend's `localStorage`-based state with server-side persistence, real payment processing, and async email notifications.

Tests require `TEST_DATABASE_URL=sqlite+aiosqlite:///:memory:` before application imports. Copy `.env.test.example` to `.env.test`; file-backed test targets are rejected. Tests verify `PRAGMA database_list` before schema changes and use a fresh test-only Redis emulator for security controls.

The default application path is absolute under `backend/`; explicit relative URLs resolve against the process working directory. Keep async and sync URLs on the same file. No existing PostgreSQL records are copied automatically.

## Quick Start

### Using Docker Compose (Recommended)

```bash
# From the project root: copy root .env.example to .env and set private secrets.
# Only for an intentional new installation (never to replace legacy records):
docker compose run --rm web python -m scripts.sqlite_database initialize --create

# Start services after schema initialization
docker compose up -d

# For an existing database, apply reviewed migrations without permitting a new file:
# docker compose run --rm web python -m scripts.sqlite_database initialize

# Seed initial data (6 categories, 24 products, admin user)
docker-compose exec web python -m scripts.seed
```

The API will be available at `http://localhost:8000`.

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env  # Edit with your settings

# Start Redis (SQLite requires no database server)
docker-compose up -d redis

# Initialize only an intentional new installation
python -m scripts.sqlite_database initialize --create
# For an existing database: python -m scripts.sqlite_database initialize

# Seed initial data
python -m scripts.seed

# Start the server
uvicorn app.main:app --reload --no-proxy-headers
```

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, router registration, lifespan
│   ├── core/                # Shared infrastructure
│   │   ├── config.py        # Pydantic Settings (env vars)
│   │   ├── database.py      # SQLAlchemy async engine + session factory
│   │   ├── security.py      # Argon2 hashing, JWT encode/decode, get_current_user
│   │   ├── rate_limit.py    # Redis-backed per-IP rate limiter
│   │   └── brute_force.py   # Redis-backed brute-force lockout
│   ├── identity/            # Bounded context: users & auth
│   │   ├── models.py        # User model
│   │   ├── schemas.py       # Pydantic request/response schemas
│   │   └── router.py        # Auth endpoints + lockout management
│   ├── catalog/             # Bounded context: products & categories
│   │   ├── models.py        # Category, Product models
│   │   ├── schemas.py       # Category/Product schemas
│   │   └── router.py        # Public + admin catalog endpoints
│   ├── inventory/           # Bounded context: stock management
│   │   ├── models.py        # Inventory, StockHold models
│   │   ├── schemas.py       # Inventory schemas
│   │   ├── service.py       # Hold/commit/release/decrement logic
│   │   └── router.py        # Stock check + admin update endpoints
│   ├── orders/              # Bounded context: order lifecycle
│   │   ├── models.py        # Order, OrderItem, OutboxEvent models
│   │   ├── schemas.py       # Order request/response schemas
│   │   ├── service.py       # place_order, cancel_order, confirm_payment
│   │   └── router.py        # Order CRUD + cancel endpoints
│   ├── payments/            # Bounded context: payment processing
│   │   ├── gateway.py       # PaymentGateway port + Flutterwave adapter
│   │   └── router.py        # Initiate + webhook endpoints
│   └── notifications/       # Bounded context: async email
│       ├── tasks.py         # Celery tasks + Resend email sender
│       └── router.py        # Test notification endpoint
│
├── alembic/                 # Database migration scripts
│   ├── env.py
│   ├── script.py.mako
│   └── versions/            # Migration files
│
├── scripts/
│   └── seed.py              # Database seeder (categories, products, admin)
│
├── tests/
│   ├── conftest.py          # Async test fixtures (client, db, auth headers)
│   ├── test_identity.py     # Auth endpoint tests
│   ├── test_catalog.py      # Catalog endpoint tests
│   └── test_orders.py       # Order lifecycle + stock tests
│
├── Dockerfile               # Python 3.12-slim
├── requirements.txt         # Python dependencies
├── alembic.ini              # Alembic configuration
├── .env                     # Local environment variables (git-ignored)
└── .env.example             # Environment variable template
```

## API Documentation

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI Schema**: `http://localhost:8000/openapi.json`

## API Endpoints

### Health Check

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/health` | No | Returns service status, name, and version |

### Authentication (`/api/v1/auth`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/register` | No | Create a new account (returns tokens) |
| `POST` | `/login` | No | Login and get access + refresh tokens |
| `POST` | `/refresh` | No | Exchange refresh token for new token pair |
| `GET` | `/me` | Yes | Get current user profile |
| `POST` | `/change-password` | Yes | Change password (requires current password) |
| `POST` | `/lockout/unlock` | Admin | Manually unlock a brute-force-locked account |
| `GET` | `/lockout/status/{email}` | Admin | Check lockout status for an email address |

### Catalog (`/api/v1/catalog`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/categories` | No | List all categories (sorted by name) |
| `GET` | `/categories/{slug}` | No | Get category by slug |
| `GET` | `/products` | No | List active products (search, filter, sort, paginate) |
| `GET` | `/products/{id}` | No | Get product detail with stock info |
| `POST` | `/admin/products` | Admin | Create a new product |
| `PUT` | `/admin/products/{id}` | Admin | Update an existing product |
| `DELETE` | `/admin/products/{id}` | Admin | Soft-delete a product (sets `is_active=false`) |

**Query parameters for `GET /catalog/products`:**

| Parameter | Type | Description |
|---|---|---|
| `category` | string | Filter by category slug (e.g. `diagnostic`) |
| `search` | string | Search in product name and description |
| `sort_by` | string | Sort field: `name` (default), `price`, or `created_at` |
| `sort_order` | string | `asc` (default) or `desc` |
| `min_price` | float | Minimum price filter |
| `max_price` | float | Maximum price filter |
| `skip` | int | Offset for pagination (default: 0) |
| `limit` | int | Page size (default: 50, max: 100) |

### Inventory (`/api/v1/inventory`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/products/{id}` | No | Check stock (total, held, committed, available) |
| `PUT` | `/admin/products/{id}` | Admin | Set total stock quantity for a product |

### Orders (`/api/v1/orders`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/` | Yes | Place a new order (server validates + prices everything) |
| `GET` | `/` | Yes | List user's orders (newest first, paginated) |
| `GET` | `/count` | Yes | Get total order count for the current user |
| `GET` | `/{id}` | Yes | Get order detail (own orders only) |
| `POST` | `/{id}/cancel` | Yes | Cancel an order and restore stock |

### Payments (`/api/v1/payments`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/initiate` | Yes | Start a Flutterwave payment for an order |
| `POST` | `/webhook` | No | Receive Flutterwave payment confirmation (HMAC-verified) |

### Notifications (`/api/v1/notifications`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/send-test` | Admin | Queue a test notification |

## Architecture

### Bounded Contexts

The backend is organized into six bounded contexts, each as a separate Python package under `app/`. This keeps domain logic isolated and makes each context independently testable.

#### 1. `identity` — User Management & Authentication

**Models**: `User` with fields: `id` (UUID), `email` (unique, indexed), `name`, `password_hash` (Argon2), `is_active`, `is_admin`, `created_at`, `updated_at`.

**Flow**:
- Registration hashes the password with Argon2 and returns a JWT token pair
- Login checks brute-force lockout first (Redis), then verifies the password, and returns tokens
- Token refresh exchanges a valid refresh token for a new access+refresh pair
- `get_current_user` is a FastAPI dependency that decodes the JWT and loads the user from the database

#### 2. `catalog` — Products & Categories

**Models**:
- `Category`: `id`, `slug` (unique, indexed), `name`, `tagline`, `icon_svg`, `created_at`
- `Product`: `id`, `sku` (unique, indexed), `name`, `description`, `price`, `category_id` (FK), `specs` (JSON), `requires_prescription`, `certification_refs`, `is_active`, `created_at`, `updated_at`

**Design decisions**:
- `specs` is a flexible JSON column — different product types have different spec sheets (weight, battery life, sterilization notes, etc.), so a rigid schema doesn't fit
- `requires_prescription` and `certification_refs` exist even though compliance workflows are out of scope — fields are easier to add now than to retrofit later
- Products are soft-deleted (`is_active=false`) rather than physically removed

#### 3. `inventory` — Stock Management

**Models**:
- `Inventory`: `product_id` (unique FK), `quantity_total`, `quantity_held`, `quantity_committed`, `updated_at`
- `StockHold`: `inventory_id` (FK), `order_id`, `quantity`, `status` (active/committed/released/expired), `expires_at`

**Key formula**: `quantity_available = quantity_total - quantity_held - quantity_committed`

**Why stock is a separate aggregate**: Stock management has its own consistency requirements (concurrent decrements, holds, expiry) that are independent of the product catalog. Keeping it separate avoids locking the product table during checkout.

**Concurrency control**: SQLite transactions acquire the write lock using `BEGIN IMMEDIATE` before stock reads. Transactions are serialized; lock acquisition waits up to 30 seconds.

**Stock lifecycle**:
1. **Hold** (on order placement): reserves stock for 15 minutes
2. **Commit** (on payment success): converts held stock to committed (deducted from available)
3. **Release** (on hold expiry or cancellation): returns held stock to available
4. **Restore** (on order cancellation): decrements committed stock

#### 4. `orders` — Order Lifecycle

**Models**:
- `Order`: `id`, `user_id` (FK), `status` (enum), shipping fields, `subtotal`, `shipping_cost`, `total`, `payment_reference`, `placed_at`, `updated_at`
- `OrderItem`: `order_id` (FK), `product_id`, `product_name`, `product_sku`, `quantity`, `unit_price`, `line_total`
- `OutboxEvent`: `event_type`, `payload` (JSON), `created_at`, `processed`, `processed_at`

**Order status flow**:
```
pending_payment → paid → processing → shipped → delivered
                  ↓
               cancelled
```

**Key behaviors**:
- **Server-side pricing**: Every line item is re-fetched from the catalog and re-priced. Client-sent prices are ignored.
- **Transactional outbox**: Order events are written to `outbox_events` in the same DB transaction as the order, then consumed asynchronously by Celery for notifications.
- **Shipping**: Existing amounts remain unchanged: free at RWF 250 or above, otherwise RWF 12.50. This task adds no shipping policy or configuration changes.
- **Cancellation guard**: Double-cancel is prevented by the status check — once cancelled, stock is never restored twice.

#### 5. `payments` — Payment Gateway

**Port interface** (`PaymentGateway` abstract class):
- `initiate_payment(PaymentInitiation) → PaymentResult`
- `verify_webhook(payload, signature) → bool`
- `verify_transaction(transaction_id) → dict | None`

**Adapters**:
- `FlutterwaveAdapter`: Real implementation using Flutterwave's API v3. Supports RWF, MTN MoMo, Airtel Money, and card payments. Webhook signature verified via HMAC-SHA256.
- `MockPaymentGateway`: Returns success immediately. Used when no `FLW_SECRET_KEY` is configured.

**Factory**: `get_payment_gateway()` returns `FlutterwaveAdapter` if credentials are present, otherwise `MockPaymentGateway`.

#### 6. `notifications` — Async Email

**Celery tasks**:
- `send_order_confirmation` — triggered on `order.placed`
- `send_payment_received` — triggered on `order.paid`
- `send_order_shipped` — triggered on `order.shipped`
- `send_order_cancelled` — triggered on `order.cancelled`

**Email delivery**: Uses Resend's REST API. In development (no API key), emails are logged to stdout. All tasks have `max_retries=3` with 60-second delay.

**Outbox processor**: `process_outbox_events` polls unprocessed `OutboxEvent` records and dispatches the appropriate Celery task based on `event_type`.

### Infrastructure

Three services orchestrated via Docker Compose; SQLite is a file shared by the web and worker backend bind mounts:

| Service | Image | Port | Purpose |
|---|---|---|---|
| `redis` | `redis:7-alpine` | 6379 | Rate limiting, brute-force protection, Celery broker + backend |
| `web` | Custom (Python 3.12-slim) | 8000 | FastAPI application server |
| `celery_worker` | Same as `web` | — | Background task processor |

The `web` and `celery_worker` services depend on the Redis health check. Existing PostgreSQL volumes remain untouched and are no longer used.

## Security Features

### Password Hashing

Passwords are hashed with **Argon2** (via `passlib[argon2]`) before storage. Argon2 is a memory-hard algorithm designed to resist GPU and ASIC attacks. Passwords are never stored in plaintext and cannot be reversed.

### JWT Authentication

- **Access tokens**: Short-lived (30 minutes), carry `sub` (user ID) and `is_admin` claims
- **Refresh tokens**: Longer-lived (7 days), carry only `sub`
- **Algorithm**: HS256 with a configurable secret key
- Tokens are stateless — no server-side session storage

### Brute-Force Protection

Redis-backed per-email tracking:
- Sliding window of 15 minutes
- After **5 failed login attempts** within the window, the account is locked for **15 minutes**
- `Retry-After` header returned on lockout (HTTP 423)
- Lockout is checked **before** password verification to avoid timing leaks
- Admin endpoints to check status (`GET /lockout/status/{email}`) and manually unlock (`POST /lockout/unlock`)

### Rate Limiting

Redis-backed per-IP fixed-window rate limiting:
- **Login**: 5 requests/minute
- **Register**: 3 requests/minute
- Returns `429 Too Many Requests` with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining` headers
- Bypass for admin JWT holders and trusted proxy IPs
- Exempt paths (e.g. `/api/v1/health`) never hit Redis

### Server-Side Validation

Every write endpoint validates input server-side using Pydantic schemas. Client-side form validation in the frontend is treated as **UX only**, never as a trust boundary. Order prices are always recomputed from the current catalog.

### Payment Security

- Card data is **never stored or logged** on the server — PCI scope is handled entirely by Flutterwave
- Webhook payloads are verified via HMAC signature (`verif-hash` header)
- Webhook handling is idempotent — payment providers retry deliveries, so duplicate events are safely ignored

### Database Safety

- **Serialized SQLite transactions** (`BEGIN IMMEDIATE`) protect concurrent stock mutations
- **Stock holds** with automatic expiry prevent abandoned checkouts from permanently reserving stock
- **Transactional outbox** ensures cross-context events are never lost
- **Soft deletes** for products preserve referential integrity in order history

## Environment Variables

See `.env.example` for the full template. Key variables:

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | SQLite async URL | `sqlite+aiosqlite:///activelifemedical.sqlite3` |
| `DATABASE_URL_SYNC` | Matching SQLite URL for Alembic | `sqlite:///activelifemedical.sqlite3` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `CELERY_BROKER_URL` | Celery broker (Redis DB 1) | `redis://localhost:6379/1` |
| `CELERY_RESULT_BACKEND` | Celery result backend (Redis DB 2) | `redis://localhost:6379/2` |
| `JWT_SECRET_KEY` | Secret for signing JWT tokens | **Must be changed in production** |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime | `30` |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime | `7` |
| `FLW_SECRET_KEY` | Flutterwave API secret key | Empty (uses mock gateway) |
| `FLW_PUBLIC_KEY` | Flutterwave public key | Empty |
| `FLW_WEBHOOK_SECRET` | Flutterwave webhook HMAC secret | Empty |
| `FLW_BASE_URL` | Flutterwave API base URL | `https://api.flutterwave.com/v3` |
| `RESEND_API_KEY` | Resend email API key | Empty (emails logged to stdout) |
| `EMAIL_FROM` | Sender email address | `noreply@activelife.rw` |
| `RATE_LIMIT_LOGIN` | Login rate limit | `5/minute` |
| `RATE_LIMIT_REGISTER` | Register rate limit | `3/minute` |
| `RATE_LIMIT_BYPASS_IPS` | Exact direct client IPs exempt from rate limiting | `[]` |
| `RATE_LIMIT_TRUSTED_PROXY_IPS` | Exact reverse proxy IPs allowed to supply a client address | `[]` |
| `JWT_ADMIN_BYPASS` | Admin users bypass rate limits | `true` |
| `BF_MAX_FAILURES` | Failed attempts before lockout | `5` |
| `BF_LOCKOUT_SECONDS` | Lockout duration (seconds) | `900` (15 min) |
| `BF_WINDOW_SECONDS` | Sliding window for failure counting | `900` (15 min) |

For a reverse proxy deployment, run Uvicorn with `--no-proxy-headers` so the
limiter receives the actual socket peer. Set `RATE_LIMIT_TRUSTED_PROXY_IPS` to
the exact IPs of controlled proxies as a JSON array. The edge proxy must replace
incoming forwarding metadata with the observed client IP, and subsequent
trusted proxies must append the address of their immediate peer to a single
`X-Forwarded-For` header. The limiter walks that chain from right to left and
uses the first address outside the trusted proxy list. Missing, duplicate,
invalid, or all-trusted chains use the socket peer's rate limit bucket.
`RATE_LIMIT_BYPASS_IPS` applies only to direct clients outside the trusted proxy
list. Deployments that previously used that setting for a reverse proxy should
move the proxy address to `RATE_LIMIT_TRUSTED_PROXY_IPS`.

## Testing

SQLITE-REF-001 validation (2026-11-23): **88 passed, 0 failed**, with one upstream Argon2 deprecation warning. This includes all 60 previously reported tests and 28 additional cases. The prior ENV-001 baseline was 53 passed and seven order serialization failures; that historical baseline is superseded.

Order creation explicitly refreshes `items` while the async session is open. Retrieval, listing and cancellation explicitly use select-in loading. Nested item schemas accept ORM attributes. Tests verify detached serialization, five-order batch loading (at most two item queries including authentication), ownership checks, cancellation responses, rollback of partially placed orders, and unchanged totals/shipping amounts. The existing OpenAPI schema is unchanged.

The existing initial migration was preserved and verified on disposable SQLite files: upgrade/downgrade, repeated initialization preserving records, and `alembic check` (no schema drift). Application lifecycle startup and SQLite persistence across separate Python processes pass. A native Uvicorn server also started against the existing application database and returned HTTP 200 from `/api/v1/health`. Online backup includes committed WAL pages; restore writes to a new file and validates integrity and foreign keys. SQLite foreign keys are enabled on each connection. Concurrent decrements and stock holds cannot reserve the last unit twice. SQL parameters and configuration validation inputs are redacted.

The application file hash and table counts were recorded before work and remained unchanged after the full regression and repeat initialization. The Product Owner confirmed use of the existing SQLite database and retention of PostgreSQL separately; no legacy records are required to be copied for this cutover. No legacy database, credential, backup or volume was deleted or modified.

Tests use a fresh fakeredis instance per test; Redis and Celery production configuration is unchanged. Container startup and real Redis/Celery/provider integration remain UNVERIFIED because the Docker daemon is unavailable. SQLite intentionally serializes transactions (`BEGIN IMMEDIATE`, 30-second busy timeout), including read transactions; production throughput has not been load-tested.

### Exact changed-file inventory

Paths are relative to the repository root and include the SQLite groundwork carried forward from ENV-001.

- `.env.example`
- `.gitignore`
- `README.md`
- `backend/.dockerignore`
- `backend/.env.example`
- `backend/.env.test.example`
- `backend/README.md`
- `backend/SECURITY-CONFIG.md`
- `backend/alembic.ini`
- `backend/alembic/env.py`
- `backend/app/catalog/models.py`
- `backend/app/core/config.py`
- `backend/app/core/database.py`
- `backend/app/core/types.py`
- `backend/app/identity/models.py`
- `backend/app/inventory/models.py`
- `backend/app/inventory/service.py`
- `backend/app/main.py`
- `backend/app/notifications/tasks.py`
- `backend/app/orders/models.py`
- `backend/app/orders/router.py`
- `backend/app/orders/schemas.py`
- `backend/app/orders/service.py`
- `backend/app/payments/gateway.py`
- `backend/app/payments/router.py`
- `backend/requirements-test.txt`
- `backend/requirements.txt`
- `backend/scripts/sqlite_database.py`
- `backend/tests/conftest.py`
- `backend/tests/db_isolation.py`
- `backend/tests/test_database_isolation.py`
- `backend/tests/test_orders.py`
- `backend/tests/test_payments.py`
- `backend/tests/test_security_config.py`
- `backend/tests/test_sqlite_operations.py`
- `docker-compose.yml`

### Remaining-integration audit

The full backend, revision history, fixtures, requirements, Compose services, worker launcher and documentation were inspected before edits. This inventory records locations at the start of SQLITE-REF-001; line numbers may move after corrections.

| Original location | Finding | Disposition |
|---|---|---|
| `docker-compose.yml:56` | Unused legacy database volume declaration | Removed declaration only; actual volume retained |
| `README.md:173` | Obsolete database name in architecture diagram | Replaced with SQLite |
| `tests/test_database_isolation.py:24,73` | Obsolete async-driver URL in rejection tests | Replaced with generic forbidden-engine input |
| `app/inventory/service.py:40,43` | Misleading row-lock documentation | Corrected to describe SQLite transaction serialization |
| `app/inventory/service.py:47,74,100,143,172,202` | Generic SQLAlchemy `with_for_update()` lock intent | Intentionally retained generic abstraction; SQLite does not emit the clause, and engine transactions provide the actual locking |
| `app/orders/service.py:99`, `app/orders/router.py:23`, `app/orders/schemas.py:25` | Unloaded new order collection and missing nested ORM conversion | Explicit async load plus nested `from_attributes` |
| `app/payments/gateway.py:22`, `app/payments/router.py:49`, `app/notifications/tasks.py:73,92` | USD default/dispatch and dollar labels | RWF-only dispatch, validation and email labels; numeric prices untouched |
| `alembic/versions/9d384d3bb830_initial_schema.py` | Only revision; generic SQLAlchemy types, constraints, JSON and enums | Preserved unchanged; SQLite migration and schema comparison verified |
| `app/core/config.py`, `app/core/database.py`, environment templates, requirements | Already used SQLite from ENV-001 | Retained; added startup/migration checks and redaction |

No backend runtime PostgreSQL driver, dialect import, connection default, extension, SQL branch or Docker database service remains. The words naming forbidden engines/drivers remain only in rejection/absence tests and historical retention notes. Generic SQLAlchemy sessions, relationships, enums, JSON, migrations and lock-intent expressions remain intact.

```bash
# Install test dependencies and configure the isolated database
pip install -r requirements-test.txt
cp .env.test.example .env.test

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=app --cov-report=html

# Run a specific test file
pytest tests/test_orders.py

# Run a specific test
pytest tests/test_orders.py::test_place_order -v
```

### Test Structure

- **`conftest.py`**: Async fixtures for the test database (create/drop tables per test), HTTP test client (`httpx.AsyncClient`), test users (regular + admin), and auth headers.
- **`test_identity.py`**: Registration, duplicate email rejection, weak password validation, login success/failure, token refresh, password change, profile retrieval.
- **`test_catalog.py`**: Category listing, product listing with search/filter/category filter, product detail, 404 handling, admin CRUD, authorization (non-admin cannot create products).
- **`test_orders.py`**: Order placement, server-side pricing verification, insufficient stock rejection, order listing, order detail, cancellation with stock restoration, double-cancel prevention, free shipping threshold.

### Test Coverage Areas

- Auth flow end-to-end (register → login → use token → refresh)
- Catalog search/filter/sort integration
- Order lifecycle with real stock interactions
- Stock concurrency (insufficient stock rejection)
- Server-side pricing (client prices are ignored)
- Cancellation idempotency (double-cancel blocked)

## Database Migrations

Alembic manages schema migrations. The initial migration (`9d384d3bb830`) captures the full schema.

```bash
# Check current migration version
alembic current

# Check for pending changes
alembic check

# Generate a new migration after model changes
alembic revision --autogenerate -m "description of change"

# Apply pending migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1

# View migration history
alembic history
```

**Workflow when modifying models:**
1. Edit the model file (e.g. `app/catalog/models.py`)
2. Run `alembic revision --autogenerate -m "what changed"`
3. Review the generated migration in `alembic/versions/`
4. Test with `alembic upgrade head` then `alembic downgrade -1`
5. Commit both the model and migration files

**Note:** The seed script (`python -m scripts.seed`) assumes tables already exist. Initialize explicitly before seeding; the seed script is intended for an empty installation and must not be rerun against existing data.

## SQLite initialization, backup and restore

Startup checks the existing persistent file and applied Alembic revision. It fails if the file is missing, ephemeral, uninitialized or on the wrong revision. It does not seed or silently create a replacement database. The CLI rejects unknown unversioned databases. To upgrade the current database repeatedly without resetting records, run from `backend`:

```bash
python -m scripts.sqlite_database initialize
```

Only an intentional new installation may use `initialize --create`. Retain revision `9d384d3bb830` for existing installations. Future SQLite table alterations should use reviewed Alembic batch migrations and be tested on a disposable copy. Downgrade examples above are for disposable development databases; they drop tables and are not a restore procedure.

Use SQLite's online backup API rather than copying only the main file while a writer is active:

```bash
# Destination must be new; neither command overwrites an existing file.
python -m scripts.sqlite_database backup activelifemedical.sqlite3 backup-2026-11-23.sqlite3
python -m scripts.sqlite_database restore backup-2026-11-23.sqlite3 restored-2026-11-23.sqlite3
```

The backup includes committed WAL data and validates SQLite integrity and foreign keys. Restore is verified on a new path. Stop both web and Celery before switching the matching async/sync URLs to the verified restored file; keep the previous database for recovery. Never delete active journal, WAL or SHM files manually. Database and sidecar files are ignored by Git and excluded from the Docker build context. The existing backend bind mount persists the SQLite file across container restarts. Protect the database and backup directories using operating-system permissions; SQLite adds no password authentication or built-in file encryption here.

## Default Credentials

After seeding:

| Role | Email | Password |
|---|---|---|
| Admin | admin@activelife.rw | Private `ADMIN_SEED_PASSWORD` supplied when seeding; no default |

## Code Conventions

- **Python 3.12+** with type hints throughout
- **FastAPI** for route definitions with Pydantic v2 for request/response validation
- **SQLAlchemy 2.0** async with mapped columns and relationships
- **UUID string** primary keys (not auto-increment integers)
- **`UTCDateTime`** for timestamp columns (UTC-aware Python values over SQLite storage)
- **Soft deletes** for products (`is_active` flag) — never hard-delete catalog data
- **Pydantic `model_config = {"from_attributes": True}`** for ORM-compatible schemas
- **One router per bounded context**, registered in `main.py` under `/api/v1/`
