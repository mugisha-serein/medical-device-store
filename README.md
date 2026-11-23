# Active Life Medical — Medical Devices E-Commerce Platform

A full-stack e-commerce platform for purchasing medical devices, built to serve clinics, hospitals, and home-care customers in East Africa and beyond. The project started as a static HTML/CSS/JavaScript storefront demo and has been extended with a production-grade FastAPI backend that replaces client-side localStorage with a real database, server-side validation, and async payment processing.

## Why This System Exists

Medical device procurement in many African markets is still fragmented — buyers call suppliers, compare paper catalogs, and track orders manually. Active Life Medical provides a modern, browsable online storefront that makes it easy to discover, compare, and order certified medical equipment across six categories.

The frontend was built as a zero-dependency static site so it works on low-bandwidth connections and can be deployed anywhere (static hosting, local intranet, file:// protocol). The backend was added to solve real problems the demo had: accounts and carts stored only in the browser, overselling due to no server-side stock tracking, no payment processing, and no email notifications. Moving these concerns server-side makes the platform viable for real use.

## Project Structure

```
activelifemedical-store/
├── index.html                  # Home page
├── products.html               # All products with search/sort/filter
├── categories.html             # Category grid
├── category.html               # Products in a category (?id=<slug>)
├── product.html                # Product detail + spec sheet (?id=<productId>)
├── about.html                  # About page
├── login.html / register.html  # Auth pages
├── cart.html                   # Shopping cart
├── checkout.html               # Shipping + payment form
├── confirmation.html           # Order confirmation (?order=<orderId>)
├── orders.html                 # Order history
├── order.html                  # Order detail (?order=<orderId>)
│
├── css/
│   └── style.css               # Single stylesheet for all pages
│
├── js/
│   ├── products.js             # Catalog data (6 categories, 24 products) + stock helpers
│   ├── auth.js                 # Auth/session logic (localStorage + sessionStorage)
│   ├── cart.js                 # Per-user cart logic
│   ├── orders.js               # Per-user order history
│   ├── featured.js             # Rotating featured products strip
│   ├── main.js                 # Shared UI: header, cart badge, toasts, escapeHtml
│   ├── layout.js               # Injects shared header/footer into every page
│   ├── forms.js                # Per-field validation, password toggles
│   └── pages/                  # One file per page (home, products, cart, etc.)
│
├── assets/
│   └── logo.png
│
├── scripts/
│   ├── serve.mjs               # Zero-dep static dev server
│   └── screenshots.mjs         # Automated screenshot capture
│
├── tests/
│   └── smoke.test.mjs          # Static integrity, JS syntax, security, headless Chrome tests
│
├── backend/
│   ├── app/                    # FastAPI application (bounded contexts)
│   │   ├── main.py             # App entrypoint, router registration
│   │   ├── core/               # Database, config, security, rate limiting, brute-force protection
│   │   ├── identity/           # User management, JWT auth
│   │   ├── catalog/            # Products, categories, spec sheets
│   │   ├── inventory/          # Stock management with serialized SQLite transactions
│   │   ├── orders/             # Order lifecycle, transactional outbox
│   │   ├── payments/           # Flutterwave gateway (hexagonal adapter pattern)
│   │   └── notifications/      # Celery tasks for async email (Resend)
│   ├── alembic/                # Database migrations
│   ├── scripts/seed.py         # Seeds 6 categories, 24 products, admin user
│   ├── tests/                  # Pytest async integration tests
│   ├── Dockerfile              # Python 3.12-slim image
│   ├── requirements.txt
│   └── .env.example
│
├── docker-compose.yml          # SQLite, Redis, FastAPI, Celery worker
├── package.json                # ESLint + Puppeteer for frontend tooling
└── eslint.config.js            # ESLint 9 flat config
```

## Tech Stack

### Frontend

| Layer | Technology | Why |
|---|---|---|
| Markup | HTML5 semantic elements | Accessible, SEO-friendly, no framework overhead |
| Styling | Single CSS file (`css/style.css`) | Zero build step, fast to load, easy to theme |
| Interactivity | Vanilla JavaScript (ES2022, `<script type="module">`) | No transpiler, no bundler, works from `file://` |
| Layout injection | `js/layout.js` injects shared header/footer | Single source of truth for navigation |
| Testing | Node.js `node:test` + Puppeteer | Smoke tests, security checks, headless Chrome render tests |
| Linting | ESLint 9 (flat config) | Consistent code style across all JS files |

### Backend

| Layer | Technology | Why |
|---|---|---|
| API framework | FastAPI 0.115 | Async Python, auto-generated OpenAPI docs, Pydantic validation |
| Database | SQLite3 (SQLAlchemy 2.0 + aiosqlite over Python sqlite3) | File persistence, transactions, JSON column support |
| Migrations | Alembic | Version-controlled schema changes |
| Auth | JWT (`python-jose`) + Argon2 (`passlib[argon2]`) | Stateless tokens, memory-hard password hashing |
| Payments | Flutterwave (via `httpx`) | Supports RWF, MTN MoMo, Airtel Money, and cards in Africa |
| Background jobs | Celery + Redis | Async email notifications, stock hold expiry, outbox processing |
| Email | Resend API | Transactional email with no self-hosted SMTP needed |
| Rate limiting | Redis-backed per-IP fixed-window | Prevents brute-force and DDoS on auth endpoints |
| Containerization | Docker Compose | One-command setup for all four services |

## Architecture

### Frontend Architecture

The frontend is a static multi-page application (MPA). Every page shares a common structure:

1. A `#site-header` placeholder that `js/layout.js` fills with the navigation bar, logo, cart badge, and auth buttons at DOMContentLoaded.
2. Shared scripts (`products.js`, `auth.js`, `cart.js`, `main.js`, `layout.js`) loaded in order.
3. A page-specific script (`js/pages/<name>.js`) that wires up that page's logic.

There are **no inline `<script>` blocks** in any HTML file — this is enforced by the smoke tests. All JavaScript runs as classic browser scripts (not ES modules), sharing one global scope. Cross-file dependencies use `/* global */` and `/* exported */` comments for ESLint.

**State management** in the demo uses `localStorage` and `sessionStorage`:
- Accounts: `localStorage` key `md_users`
- Sessions: `sessionStorage` key `md_session` (4-hour expiry)
- Cart: per-user in `localStorage` (`md_cart_<userId>`)
- Orders: per-user in `localStorage` (`md_orders_<userId>`, capped at 20)
- Stock: overrides in `localStorage` (`md_stock`), starting from the catalog baseline in `js/products.js`

The backend replaces the authoritative state (accounts, orders, stock) with server-side persistence. Cart can remain client-side pre-checkout; stock is reconciled against the live API when an order is placed.

### Backend Architecture

The backend follows a **bounded-context architecture** (inspired by Domain-Driven Design). Each context is a separate Python package under `backend/app/` with its own models, schemas, and router:

#### 1. `identity` — User Management & Authentication

- **Models**: `User` (id, email, name, password_hash, is_active, is_admin)
- **Endpoints**: register, login, token refresh, get current user, change password, admin lockout management
- **Security**: Argon2 password hashing, JWT access tokens (30 min) + refresh tokens (7 days), brute-force lockout via Redis (5 failures → 15 min lock)

#### 2. `catalog` — Products & Categories

- **Models**: `Category` (slug, name, tagline, icon_svg), `Product` (sku, name, description, price, specs JSON, requires_prescription, certification_refs)
- **Endpoints**: list/get categories, list/get products (with search, filter, sort, pagination), admin CRUD
- **Design**: `specs` is a flexible JSON field to accommodate different spec sheets per product type. Regulatory fields (`requires_prescription`, `certification_refs`) exist even though compliance workflows are out of scope — they prevent retrofitting later.

#### 3. `inventory` — Stock Management

- **Models**: `Inventory` (quantity_total, quantity_held, quantity_committed), `StockHold` (order_id, quantity, status, expires_at)
- **Key behavior**: Stock is its own aggregate, not a column on Product. Transactions acquire a SQLite write lock with `BEGIN IMMEDIATE` before inventory reads to prevent overselling.
- **Stock holds**: When an order is placed, stock is held (not committed) for 15 minutes. If payment succeeds, the hold is committed. If the hold expires or the order is cancelled, the held quantity is released back to available stock.
- **Formulas**: `quantity_available = quantity_total - quantity_held - quantity_committed`

#### 4. `orders` — Order Lifecycle

- **Models**: `Order` (status, shipping fields, totals), `OrderItem` (frozen product snapshot: name, sku, unit_price, line_total), `OutboxEvent` (event_type, payload, processed)
- **Lifecycle**: `pending_payment → paid → processing → shipped → delivered`, plus `cancelled`
- **Server-side pricing**: Every order placement re-validates and re-prices all line items against the current catalog. The server never trusts client-sent prices.
- **Transactional outbox**: Events (`order.placed`, `order.paid`, `order.cancelled`) are written to the `outbox_events` table in the same transaction as the order, then consumed asynchronously by Celery tasks for notifications.
- **Cancellation**: Restores stock exactly once. Double-cancel is guarded by the order status check.

#### 5. `payments` — Payment Gateway

- **Port interface**: `PaymentGateway` (abstract base class) with `initiate_payment`, `verify_webhook`, `verify_transaction`
- **Flutterwave adapter**: Handles RWF, MTN MoMo, Airtel Money, and card payments. Webhook endpoint verifies HMAC signature. Idempotent handling (PSPs retry deliveries).
- **Mock gateway**: Used when no Flutterwave credentials are configured (development mode).
- **Factory**: `get_payment_gateway()` returns `FlutterwaveAdapter` if `FLW_SECRET_KEY` is set, otherwise `MockPaymentGateway`.

#### 6. `notifications` — Async Email

- **Celery tasks**: `send_order_confirmation`, `send_payment_received`, `send_order_shipped`, `send_order_cancelled`
- **Email via Resend**: HTML emails sent through Resend's REST API. In development (no API key), emails are logged to stdout.
- **Outbox processor**: Periodic task polls unprocessed `OutboxEvent` records and dispatches the appropriate Celery task.

### Infrastructure

```
┌─────────────────────────────────────────────────┐
│                  Docker Compose                  │
│                                                  │
│  ┌──────────┐  ┌───────┐  ┌──────┐  ┌────────┐ │
│  │ SQLite   │  │ Redis │  │ Web  │  │ Celery │ │
│  │   16     │  │  7    │  │ API  │  │ Worker │ │
│  │          │  │       │  │:8000 │  │        │ │
│  └──────────┘  └───────┘  └──────┘  └────────┘ │
│       │            │          │          │       │
│       └────────────┴──────────┴──────────┘       │
│              All services share a network         │
└─────────────────────────────────────────────────┘
```

- **SQLite3**: Primary database for application state, stored in `backend/activelifemedical.sqlite3`. Redis remains the security cache and Celery broker.
- **Redis 7**: Used for rate limiting, brute-force protection, Celery broker, and Celery result backend.
- **FastAPI web server**: Serves the REST API on port 8000.
- **Celery worker**: Processes async tasks (email notifications, outbox events).

## Getting Started

### Frontend (Static Demo)

```bash
# Option 1: Open directly in a browser
open index.html

# Option 2: Dev server (Node.js)
npm install
npm run dev
# Visit http://localhost:8000
```

### Backend (Docker Compose — Recommended)

```bash
# From the repository root; configure private secrets in root .env
cp .env.example .env

# Explicitly initialize a new installation before starting the web service
docker compose run --rm web python -m scripts.sqlite_database initialize --create
docker compose up -d

# Seed initial data (6 categories, 24 products, admin user)
docker-compose exec web python -m scripts.seed
```

The API is now at `http://localhost:8000` with interactive docs at `/docs`.

### Backend (Local Development)

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env

# Start Redis (SQLite requires no database server)
docker-compose up -d redis

# Initialize an intentional new installation
python -m scripts.sqlite_database initialize --create
# Existing database: python -m scripts.sqlite_database initialize

# Seed data
python -m scripts.seed

# Start the server
uvicorn app.main:app --reload
```

### Default Credentials (After Seeding)

| Role | Email | Password |
|---|---|---|
| Admin | admin@activelife.rw | Private `ADMIN_SEED_PASSWORD` supplied when seeding; no default |

## API Reference

All endpoints are versioned under `/api/v1/`. Interactive documentation is available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### Authentication (`/api/v1/auth`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/register` | No | Create account, returns tokens |
| `POST` | `/login` | No | Login, returns access + refresh tokens |
| `POST` | `/refresh` | No | Exchange refresh token for new tokens |
| `GET` | `/me` | Yes | Get current user profile |
| `POST` | `/change-password` | Yes | Change password (requires current password) |

### Catalog (`/api/v1/catalog`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/categories` | No | List all categories |
| `GET` | `/categories/{slug}` | No | Get category by slug |
| `GET` | `/products` | No | List products (search, filter, sort, paginate) |
| `GET` | `/products/{id}` | No | Get product detail with stock |
| `POST` | `/admin/products` | Admin | Create product |
| `PUT` | `/admin/products/{id}` | Admin | Update product |
| `DELETE` | `/admin/products/{id}` | Admin | Soft-delete product |

**Query parameters for `GET /products`:**
- `category` — filter by category slug
- `search` — search in name and description
- `sort_by` — `name`, `price`, or `created_at`
- `sort_order` — `asc` or `desc`
- `min_price`, `max_price` — price range filter
- `skip`, `limit` — pagination (default: 0, 50; max: 100)

### Inventory (`/api/v1/inventory`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/products/{id}` | No | Check stock (total, held, committed, available) |
| `PUT` | `/admin/products/{id}` | Admin | Set total stock for a product |

### Orders (`/api/v1/orders`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/` | Yes | Place new order (server validates + prices) |
| `GET` | `/` | Yes | List user's orders (newest first, paginated) |
| `GET` | `/count` | Yes | Get total order count |
| `GET` | `/{id}` | Yes | Get order detail (own orders only) |
| `POST` | `/{id}/cancel` | Yes | Cancel order, restore stock |

### Payments (`/api/v1/payments`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/initiate` | Yes | Start Flutterwave payment flow |
| `POST` | `/webhook` | No | Receive payment confirmation (signature-verified) |

### Notifications (`/api/v1/notifications`)

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/send-test` | Admin | Send test notification (admin only) |

## Security Features

### Authentication & Authorization

- **Argon2 password hashing** — memory-hard algorithm resistant to GPU/ASIC attacks
- **JWT tokens** — short-lived access tokens (30 min) with longer refresh tokens (7 days)
- **Admin role** — `is_admin` flag checked on every protected endpoint
- **No plaintext passwords** — hashed before storage, verified via constant-time comparison

### Brute-Force Protection

- Redis-backed per-email tracking with sliding window
- After 5 failed login attempts within 15 minutes, the account is locked for 15 minutes
- `Retry-After` header returned on lockout
- Admin endpoints to check status and manually unlock accounts

### Rate Limiting

- Per-IP fixed-window rate limiting on auth endpoints:
  - Login: 5 requests/minute
  - Register: 3 requests/minute
- Bypass for admin JWT holders and trusted proxy IPs
- Returns `429 Too Many Request` with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining` headers

### Server-Side Validation

- Every write endpoint validates input server-side regardless of client-side checks
- Client-side form validation (`js/forms.js`) is treated as UX only, never as a trust boundary
- Order pricing is always computed server-side from the current catalog — client-sent prices are ignored

### Payment Security

- Card data is **never stored or logged** on the server — PCI scope is handled entirely by Flutterwave
- Webhook payloads are verified via HMAC signature (`verif-hash` header)
- Webhook handling is idempotent (payment providers retry deliveries)

### Frontend Security

- `escapeHtml()` in `js/main.js` neutralizes all user-generated content before DOM insertion
- Open-redirect prevention in auth flow (`getNextUrl()` rejects absolute URLs, protocol-relative URLs, and non-HTTP schemes)
- No inline `<script>` blocks (enforced by smoke tests)
- Content Security: all assets are local (no external script loading)

## Testing

### Frontend Tests

```bash
npm install          # Install ESLint + Puppeteer
npm run lint         # ESLint (must pass clean)
npm run smoke        # Comprehensive smoke tests
npm run check        # Lint + smoke together
```

The smoke test suite covers:
1. **Static integrity** — every page serves 200, all referenced assets exist, header/footer placeholders are wired
2. **JS syntax** — all files parse without errors
3. **Security helpers** — open-redirect guard, escapeHtml, order history isolation, stock clamping
4. **Headless Chrome** — renders every page, verifies DOM markers, catches runtime JS errors
5. **Full user flows** — register → add to cart → checkout → cancel order → verify stock restoration
6. **Mobile nav** — hamburger menu opens/closes, no horizontal scroll on 390px viewport
7. **Featured rotation** — cycles through the pool by date, persists per session, excludes out-of-stock items

### Backend Tests

```bash
cd backend

# Install test dependencies and configure the isolated database
pip install -r requirements-test.txt
cp .env.test.example .env.test

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html
```

Test files:
- `test_identity.py` — registration, login, token refresh, password change, duplicate email rejection
- `test_catalog.py` — category listing, product search/filter, admin CRUD, authorization checks
- `test_orders.py` — order placement, server-side pricing, stock validation, cancellation, double-cancel guard, free shipping threshold

### Database Migrations

Alembic manages schema versioning. The initial migration (`3cdedb7b55b0`) captures the full schema.

```bash
cd backend

# Check current version
alembic current

# Generate migration after model changes
alembic revision --autogenerate -m "description"

# Apply all pending migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

**Important:** Always run `alembic upgrade head` before `python -m scripts.seed`. The seed script assumes tables already exist.

## Environment Variables

See `backend/.env.example` for the full list. Key variables:

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | SQLite async URL | `sqlite+aiosqlite:///activelifemedical.sqlite3` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `JWT_SECRET_KEY` | Secret for signing JWT tokens | Must be changed in production |
| `FLW_SECRET_KEY` | Flutterwave API secret key | Empty (uses mock gateway) |
| `FLW_WEBHOOK_SECRET` | Flutterwave webhook HMAC secret | Empty |
| `RESEND_API_KEY` | Resend email API key | Empty (emails logged to stdout) |
| `RATE_LIMIT_LOGIN` | Login rate limit | `5/minute` |
| `BF_MAX_FAILURES` | Failed attempts before lockout | `5` |
| `BF_LOCKOUT_SECONDS` | Lockout duration | `900` (15 min) |

## Code Conventions

- **JavaScript**: ES2022, double quotes, semicolons, 2-space indent. Cross-file globals via `/* global */` / `/* exported */` comments.
- **Python**: FastAPI conventions, Pydantic v2 schemas, SQLAlchemy 2.0 async. Each bounded context is a package with `models.py`, `schemas.py`, `router.py`, and optionally `service.py`.
- **Database**: UUID string primary keys, `DateTime(timezone=True)` for all timestamps, soft-delete for products (`is_active`).
- **API**: RESTful, versioned (`/api/v1/`), JSON request/response, OpenAPI auto-generated from code.

## What's Out of Scope

- Admin panel UI (separate project)
- Rwanda FDA device registration / compliance workflow
- Multi-currency / tax handling
- Returns/refunds workflow beyond order cancellation
- Real frontend rewrite to use the API (the demo frontend still uses localStorage for most state)

## License

This is a demo/prototype project. Not licensed for production use without significant additional work on security, compliance, and infrastructure.
