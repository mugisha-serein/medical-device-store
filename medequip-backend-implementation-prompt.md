# Active Life Medical — Backend Implementation Prompt

## Role
You are a senior backend engineer implementing a production-grade e-commerce
backend for Active Life Medical, a medical devices storefront. The existing frontend is
static HTML/CSS/vanilla JS with all state in localStorage/sessionStorage —
that state model is being replaced by a real API. Fix root causes, not
symptoms. No placeholders, no TODO stubs, no "in a real app you would..."
comments. If a requirement is ambiguous or a decision has real tradeoffs,
stop and ask before implementing — do not guess and move on.

## Stack
- Django 5 + Django REST Framework (reuse linkapro's conventions: DDD,
  hexagonal architecture, bounded contexts as Django apps, CQRS where it
  earns its complexity, transactional outbox for cross-context events)
- PostgreSQL 16
- Celery + Redis (async: emails, stock-hold expiry, notifications)
- Argon2 for password hashing (via django-argon2)
- JWT auth (access + refresh, short-lived access token)
- Payment: Flutterwave as primary PSP (supports RWF, MTN MoMo, Airtel
  Money, and cards) — integrate behind a `PaymentGateway` port so a second
  provider can be added without touching domain code

## Bounded contexts to implement (as separate Django apps)

### 1. `identity`
- User registration, login, logout, token refresh, password reset
  (reset token flow: never log or expose the raw token outside the email
  send path — apply the same constraint you've used for linkapro's Resend
  migration)
- Argon2 password hashing, no plaintext or reversible storage anywhere
- Session/token revocation on logout and password change
- Rate limiting on login and registration endpoints

### 2. `catalog`
- Products, categories, spec sheets — model exactly what's in
  `js/products.js` today (6 categories, per-product spec fields: weight,
  dimensions, sterilization notes, warranty)
- Admin-only write access; public read endpoints with search/sort/filter
  matching what `products.html` currently does client-side
- Field for regulatory status (e.g. `requires_prescription`,
  `certification_refs`) even if verification workflow is out of scope —
  the field must exist so it isn't a retrofit later

### 3. `inventory`
- Stock as its own aggregate, not a field bolted onto `catalog.Product`
- Decrement on order placement inside a DB transaction with row-level
  locking (`select_for_update`) — this is the fix for the oversell bug in
  the current localStorage implementation; make it impossible for two
  concurrent orders to both succeed on the last unit
- Stock holds: reserve stock when an order enters checkout, release on
  timeout (Celery task) or explicit cancellation, commit on payment success

### 4. `orders`
- Order lifecycle: `pending_payment → paid → processing → shipped →
  delivered`, plus `cancelled`
- Server re-validates and re-prices every line item against current
  catalog/stock state at order-placement time — never trust client-sent
  prices or totals
- Transactional outbox for `order.placed`, `order.paid`, `order.cancelled`
  events, consumed by `notifications`
- Cancellation restores stock exactly once (guard against double-cancel,
  same invariant as the current frontend logic — keep it, just move it
  server-side and transactional)
- Per-user order history endpoint, paginated, with detail lookup

### 5. `payments`
- `PaymentGateway` port (hexagonal boundary) with a Flutterwave adapter
- Webhook endpoint for async payment confirmation, signature-verified
- No card data ever stored or logged on our side — PSP handles PCI scope
- Idempotent webhook handling (PSPs retry deliveries)

### 6. `notifications`
- Celery tasks triggered off the orders outbox: order confirmation,
  payment received, shipped, cancelled
- Email via Resend (reuse the linkapro Resend integration pattern —
  raw tokens/secrets never enter the outbox payload)

## API contract
- REST, versioned under `/api/v1/`
- OpenAPI schema generated from DRF (drf-spectacular), not hand-written
  and left to drift
- Every write endpoint validates server-side regardless of what the
  existing frontend's `js/forms.js` already checks client-side — treat
  client validation as UX only, never as a trust boundary

## Frontend integration
- Point `js/auth.js`, `js/cart.js`, `js/orders.js` at the new API instead
  of localStorage/sessionStorage for anything that must be authoritative
  (accounts, orders, stock). Cart can stay client-side pre-checkout;
  reconcile against live stock server-side at checkout, same as today's
  "re-reads live stock when order is placed" behavior — just move the
  source of truth server-side
- Do not touch `js/products.js` catalog data model conventions more than
  necessary — map it onto the new `catalog` schema field-for-field so the
  existing page rendering logic keeps working
- `checkout.html`'s re-check-session-at-submit behavior stays; add a
  re-check-stock-at-submit call against the live API

## Non-negotiables carried over from your standards
- No dead code, no over-engineering, no speculative abstraction beyond
  what these six contexts need
- Flag any blocker (ambiguous requirement, missing decision, infra gap)
  immediately and honestly rather than working around it silently
- Test coverage per layer (domain logic unit-tested, API endpoints
  integration-tested) enforced in CI, matching your existing linkapro
  per-layer coverage setup

## Explicitly out of scope for this prompt
- Admin panel UI (separate prompt)
- Rwanda FDA device registration / compliance workflow (separate prompt,
  legal-adjacent, needs your input on actual requirements)
- Multi-currency / tax handling
- Returns/refunds workflow beyond order cancellation

## Deliverable
Working Django project with the six apps above, migrations, DRF
endpoints, Celery task definitions, Flutterwave adapter (sandbox creds
via env var, never hardcoded), and a docker-compose.yml matching
linkapro's existing service conventions (Postgres, Redis, web, celery
worker). Do not scaffold a frontend rewrite — this prompt is backend +
integration only.
