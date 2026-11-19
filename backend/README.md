# Active Life Medical Backend API

FastAPI backend for the Active Life Medical medical devices e-commerce platform. This API replaces the demo frontend's `localStorage`-based state with server-side persistence, real payment processing, and async email notifications.

## Quick Start

### Using Docker Compose (Recommended)

```bash
# From the project root
docker-compose up -d

# Run database migrations
docker-compose exec web alembic upgrade head

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

# Start PostgreSQL and Redis (or use Docker)
docker-compose up -d postgres redis

# Run migrations
alembic upgrade head

# Seed initial data
python -m scripts.seed

# Start the server
uvicorn app.main:app --reload
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

**Concurrency control**: All stock mutations use `SELECT ... FOR UPDATE` (row-level locking) so two concurrent orders cannot both succeed when only one unit remains.

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
- **Shipping**: Free over $250, otherwise $12.50.
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

Four services orchestrated via Docker Compose:

| Service | Image | Port | Purpose |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5432 | Primary database |
| `redis` | `redis:7-alpine` | 6379 | Rate limiting, brute-force protection, Celery broker + backend |
| `web` | Custom (Python 3.12-slim) | 8000 | FastAPI application server |
| `celery_worker` | Same as `web` | — | Background task processor |

All services have health checks configured. The `web` and `celery_worker` services depend on `postgres` and `redis` being healthy before starting.

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

- **Row-level locking** (`SELECT ... FOR UPDATE`) prevents overselling on concurrent orders
- **Stock holds** with automatic expiry prevent abandoned checkouts from permanently reserving stock
- **Transactional outbox** ensures cross-context events are never lost
- **Soft deletes** for products preserve referential integrity in order history

## Environment Variables

See `.env.example` for the full template. Key variables:

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string (async) | `postgresql+asyncpg://activelifemedical:activelifemedical@localhost:5432/activelifemedical` |
| `DATABASE_URL_SYNC` | PostgreSQL connection string (sync, for Alembic) | `postgresql://activelifemedical:activelifemedical@localhost:5432/activelifemedical` |
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
| `RATE_LIMIT_BYPASS_IPS` | IPs exempt from rate limiting | `[]` |
| `JWT_ADMIN_BYPASS` | Admin users bypass rate limits | `true` |
| `BF_MAX_FAILURES` | Failed attempts before lockout | `5` |
| `BF_LOCKOUT_SECONDS` | Lockout duration (seconds) | `900` (15 min) |
| `BF_WINDOW_SECONDS` | Sliding window for failure counting | `900` (15 min) |

## Testing

```bash
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

Alembic manages schema migrations. The initial migration (`3cdedb7b55b0`) captures the full schema.

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

**Note:** The seed script (`python -m scripts.seed`) assumes tables already exist. Always run `alembic upgrade head` before seeding.

## Default Credentials

After seeding:

| Role | Email | Password |
|---|---|---|
| Admin | admin@activelife.rw | admin123456 |

## Code Conventions

- **Python 3.12+** with type hints throughout
- **FastAPI** for route definitions with Pydantic v2 for request/response validation
- **SQLAlchemy 2.0** async with mapped columns and relationships
- **UUID string** primary keys (not auto-increment integers)
- **`DateTime(timezone=True)`** for all timestamp columns
- **Soft deletes** for products (`is_active` flag) — never hard-delete catalog data
- **Pydantic `model_config = {"from_attributes": True}`** for ORM-compatible schemas
- **One router per bounded context**, registered in `main.py` under `/api/v1/`
