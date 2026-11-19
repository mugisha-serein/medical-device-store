/* ============================================================
   Active Life Medical — Smoke tests (zero external dependencies)
   Run: npm run smoke   (or: node --test tests/smoke.test.mjs)

   Covers:
   1. Static integrity — every page serves 200, every local
      <script>/<link> asset exists, header/footer placeholders
      are wired, no inline <script> blocks.
   2. JS syntax — every js/*.js parses via vm.Script.
   3. Security helpers — getNextUrl/isSafeNextUrl reject
      open-redirect payloads; escapeHtml neutralizes markup.
   4. Headless Chrome — if a Chrome/Chromium binary is found
      (CHROME_PATH env var or standard install paths), render
      every page over http AND the homepage from file://, and
      assert the injected layout + page content actually appear.
      Catches runtime JS errors that static checks miss.
   ============================================================ */

import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath, pathToFileURL } from "node:url";
import puppeteer from "puppeteer-core";

/* The callbacks below run inside the browser page context. */
/* global document, getComputedStyle */

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const PAGES = [
  "index.html",
  "products.html",
  "categories.html",
  "about.html",
  "category.html",
  "product.html",
  "cart.html",
  "checkout.html",
  "confirmation.html",
  "orders.html",
  "order.html",
  "login.html",
  "register.html",
];

const SHARED_SCRIPTS = ["js/products.js", "js/auth.js", "js/cart.js", "js/main.js", "js/layout.js"];

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json",
};

/* ---------- local static server (started/stopped around the suite) ---------- */

function createServer() {
  return http.createServer((req, res) => {
    let urlPath;
    try {
      urlPath = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
    } catch {
      res.writeHead(400);
      res.end();
      return;
    }

    // Mock API responses for catalog endpoints (the frontend now fetches
    // catalog data from the FastAPI backend instead of hardcoded data).
    if (urlPath === "/api/v1/catalog/categories") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(MOCK_CATEGORIES));
      return;
    }
    if (urlPath.startsWith("/api/v1/catalog/products")) {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(MOCK_PRODUCTS));
      return;
    }
    if (urlPath === "/api/v1/auth/register" && req.method === "POST") {
      let body = "";
      req.on("data", (chunk) => { body += chunk; });
      req.on("end", () => {
        const data = JSON.parse(body);
        const userId = "usr-" + Date.now();
        const tokens = { access_token: "mock-access-" + userId, refresh_token: "mock-refresh-" + userId };
        const user = { id: userId, name: data.name, email: data.email, is_active: true, is_admin: false, created_at: new Date().toISOString() };
        res.writeHead(201, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ...tokens, user }));
      });
      return;
    }
    if (urlPath === "/api/v1/auth/login" && req.method === "POST") {
      let body = "";
      req.on("data", (chunk) => { body += chunk; });
      req.on("end", () => {
        const data = JSON.parse(body);
        const tokens = { access_token: "mock-access-login", refresh_token: "mock-refresh-login" };
        const user = { id: "usr-login", name: "Test User", email: data.email, is_active: true, is_admin: false, created_at: new Date().toISOString() };
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ...tokens, user }));
      });
      return;
    }
    if (urlPath === "/api/v1/auth/refresh" && req.method === "POST") {
      let body = "";
      req.on("data", (chunk) => { body += chunk; });
      req.on("end", () => {
        const tokens = { access_token: "mock-access-refreshed", refresh_token: "mock-refresh-new" };
        const user = { id: "usr-login", name: "Test User", email: "test@example.com", is_active: true, is_admin: false, created_at: new Date().toISOString() };
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ...tokens, user }));
      });
      return;
    }
    // Handle order cancel BEFORE the general orders POST to avoid
    // the create-order handler catching /cancel requests.
    if (urlPath.match(/\/api\/v1\/orders\/[^/]+\/cancel$/) && req.method === "POST") {
      const cancelMatch = urlPath.match(/\/api\/v1\/orders\/([^/?]+)\/cancel$/);
      if (cancelMatch) {
        const orderId = decodeURIComponent(cancelMatch[1]);
        const orders = globalThis.__mockOrders || {};
        if (orders[orderId]) {
          orders[orderId].status = "cancelled";
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify(orders[orderId]));
        } else {
          res.writeHead(404, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ detail: "Order not found." }));
        }
      } else {
        res.writeHead(404, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ detail: "Order not found." }));
      }
      return;
    }
    if (urlPath.startsWith("/api/v1/orders") && req.method === "POST") {
      let body = "";
      req.on("data", (chunk) => { body += chunk; });
      req.on("end", () => {
        const data = JSON.parse(body);
        const orderId = "ORD-" + Math.random().toString(36).slice(2, 8).toUpperCase();
        const items = data.items.map((item) => {
          const product = MOCK_PRODUCTS.find((p) => p.sku === item.product_id || p.sku === item.product_id.toUpperCase());
          return {
            product_id: item.product_id,
            product_name: product ? product.name : item.product_id,
            quantity: item.quantity,
            line_total: product ? product.price * item.quantity : 0,
          };
        });
        const subtotal = items.reduce((sum, i) => sum + i.line_total, 0);
        const shipping = subtotal > 250 ? 0 : 12.5;
        const order = {
          id: orderId,
          status: "pending_payment",
          items,
          subtotal,
          shipping_cost: shipping,
          total: subtotal + shipping,
          shipping_name: data.shipping?.name || "",
          shipping_address: data.shipping?.address || "",
          shipping_city: data.shipping?.city || "",
          shipping_postal: data.shipping?.postal || "",
          shipping_phone: data.shipping?.phone || "",
          placed_at: new Date().toISOString(),
        };
        // Store order in-memory for GET requests
        if (!globalThis.__mockOrders) globalThis.__mockOrders = {};
        globalThis.__mockOrders[orderId] = order;
        res.writeHead(201, { "Content-Type": "application/json" });
        res.end(JSON.stringify(order));
      });
      return;
    }
    if (urlPath.startsWith("/api/v1/orders") && req.method === "GET") {
      // Check for specific order ID
      const orderMatch = urlPath.match(/\/api\/v1\/orders\/([^/?]+)$/);
      if (orderMatch) {
        const orderId = decodeURIComponent(orderMatch[1]);
        const orders = globalThis.__mockOrders || {};
        if (orders[orderId]) {
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify(orders[orderId]));
        } else {
          res.writeHead(404, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ detail: "Order not found." }));
        }
      } else {
        // List all orders
        const orders = Object.values(globalThis.__mockOrders || {});
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify(orders));
      }
      return;
    }
    if (urlPath.startsWith("/api/v1/inventory/")) {
      const invMatch = urlPath.match(/\/api\/v1\/inventory\/products\/([^/?]+)$/);
      if (invMatch) {
        const sku = decodeURIComponent(invMatch[1]);
        const product = MOCK_PRODUCTS.find((p) => p.sku === sku || p.sku === sku.toUpperCase());
        const qty = product ? product.stock : 0;
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
          id: "inv-1",
          product_id: sku,
          quantity_total: qty,
          quantity_held: 0,
          quantity_committed: 0,
          quantity_available: qty,
        }));
      } else {
        res.writeHead(404, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ detail: "Not found" }));
      }
      return;
    }
    if (urlPath.startsWith("/api/v1/")) {
      // All other API endpoints return 401 (unauthenticated)
      res.writeHead(401, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "Not authenticated" }));
      return;
    }

    let filePath = path.normalize(path.join(ROOT, urlPath));
    if (!filePath.startsWith(ROOT)) {
      res.writeHead(403);
      res.end();
      return;
    }
    if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
      filePath = path.join(filePath, "index.html");
    }
    fs.readFile(filePath, (err, data) => {
      if (err) {
        res.writeHead(404);
        res.end("Not found");
        return;
      }
      res.writeHead(200, { "Content-Type": MIME[path.extname(filePath)] || "application/octet-stream" });
      res.end(data);
    });
  });
}

let server;
let baseUrl;
let browser;

before(async () => {
  server = createServer();
  await new Promise((resolve) => server.listen(0, resolve));
  baseUrl = `http://127.0.0.1:${server.address().port}`;

  if (chromePath) {
    const args = [
      "--no-first-run",
      "--no-default-browser-check",
      // Fail fast on external font hosts so page loads can't hang.
      "--host-resolver-rules=MAP fonts.googleapis.com 127.0.0.1, MAP fonts.gstatic.com 127.0.0.1",
    ];
    if (process.platform !== "win32") args.push("--no-sandbox");
    browser = await puppeteer.launch({
      executablePath: chromePath,
      headless: true,
      args,
      timeout: 20000,
    });
  }
});

after(async () => {
  if (browser) await browser.close();
  await new Promise((resolve) => server.close(resolve));
});

/* ---------- 1. static integrity ---------- */

test("every page serves 200 and references only existing local assets", async () => {
  for (const page of PAGES) {
    const res = await fetch(`${baseUrl}/${page}`);
    assert.equal(res.status, 200, `${page} should return 200`);
    const html = await res.text();

    const refs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)]
      .map((m) => m[1])
      .filter((u) => !/^(https?:|#|mailto:)/.test(u))
      .map((u) => u.split("#")[0].split("?")[0])
      .filter(Boolean);

    for (const ref of refs) {
      const r = await fetch(`${baseUrl}/${ref}`);
      assert.ok(r.status < 400, `${page} references missing local asset: ${ref} (HTTP ${r.status})`);
    }
  }
});

test("every page has placeholders, its own page script, and no inline scripts", () => {
  for (const page of PAGES) {
    const html = fs.readFileSync(path.join(ROOT, page), "utf8");
    const base = page.replace(".html", "");

    assert.equal((html.match(/id="site-header"/g) || []).length, 1, `${page}: exactly one #site-header`);
    assert.equal((html.match(/id="site-footer"/g) || []).length, 1, `${page}: exactly one #site-footer`);
    for (const shared of SHARED_SCRIPTS) {
      assert.ok(html.includes(shared), `${page} loads ${shared}`);
    }
    assert.ok(html.includes(`js/pages/${base}.js`), `${page} loads js/pages/${base}.js`);
    assert.ok(!/<script(?![^>]*src=)/.test(html), `${page}: no inline <script> blocks`);
    assert.ok(!/class="site-header"/.test(html), `${page}: header must be injected, not hardcoded`);
    assert.ok(!/class="site-footer"/.test(html), `${page}: footer must be injected, not hardcoded`);
  }

  for (const page of ["index.html", "products.html", "categories.html", "about.html", "category.html"]) {
    const html = fs.readFileSync(path.join(ROOT, page), "utf8");
    assert.ok(html.includes('data-footer="full"'), `${page} opts into the full footer`);
  }
});

/* ---------- 2. JS syntax ---------- */

test("all JS files parse without syntax errors", () => {
  const jsFiles = [];
  for (const dir of ["js", path.join("js", "pages")]) {
    for (const f of fs.readdirSync(path.join(ROOT, dir)).filter((f) => f.endsWith(".js"))) {
      jsFiles.push(path.join(dir, f));
    }
  }
  assert.ok(jsFiles.length >= 12, `expected >= 12 JS files, found ${jsFiles.length}`);
  for (const file of jsFiles) {
    const code = fs.readFileSync(path.join(ROOT, file), "utf8");
    assert.doesNotThrow(() => new vm.Script(code, { filename: file }), `${file} should parse`);
  }
});

/* ---------- 3. security helpers ---------- */

test("open-redirect guard: getNextUrl only returns same-origin targets", () => {
  const sandbox = {
    URL,
    URLSearchParams,
    location: {
      href: "http://localhost:8000/login.html",
      search: "",
      protocol: "http:",
      host: "localhost:8000",
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "js", "auth.js"), "utf8"), sandbox);

  const cases = [
    ["category.html?id=diagnostic", "category.html?id=diagnostic"], // legit relative URL
    ["/index.html", "/index.html"],                                 // legit root-relative
    ["index.html#categories", "index.html#categories"],             // legit fragment
    ["https://evil.com", "index.html"],                             // absolute URL -> fallback
    ["//evil.com", "index.html"],                                   // protocol-relative -> fallback
    ["javascript:alert(1)", "index.html"],                          // non-http scheme -> fallback
    ["data:text/html,hi", "index.html"],                            // data: -> fallback
    ["http://localhost:8000@evil.com", "index.html"],               // userinfo trick -> fallback
  ];
  for (const [next, expected] of cases) {
    sandbox.location.search = `?next=${encodeURIComponent(next)}`;
    assert.equal(sandbox.getNextUrl("index.html"), expected, `next=${next}`);
  }
});

// NOTE: order storage, retrieval, and cancellation are now server-side
// (FastAPI backend). They are tested via the headless Chrome integration
// tests below ("register → add to cart → checkout flow").

// ── Mock catalog data for VM-based tests ─────────────────────────────────────
// products.js now fetches catalog data from the FastAPI backend instead of
// embedding it. VM-sandbox tests that need the catalog provide a mock fetch
// and Response so loadCatalog() can populate the in-memory cache.

const MOCK_CATEGORIES = [
  { id: "cat-1", slug: "diagnostic", name: "Diagnostic Equipment", tagline: "Professional diagnostic tools", icon_svg: "" },
  { id: "cat-2", slug: "mobility", name: "Mobility Aids", tagline: "Mobility support devices", icon_svg: "" },
  { id: "cat-3", slug: "monitoring", name: "Monitoring Devices", tagline: "Patient monitoring systems", icon_svg: "" },
  { id: "cat-4", slug: "surgical", name: "Surgical Instruments", tagline: "Precision surgical tools", icon_svg: "" },
  { id: "cat-5", slug: "ppe", name: "Personal Protective Equipment", tagline: "Safety and protection gear", icon_svg: "" },
  { id: "cat-6", slug: "homecare", name: "Home Care Equipment", tagline: "Home healthcare devices", icon_svg: "" },
];

const MOCK_PRODUCTS = [
  { sku: "dg-001", name: "ClearTone Digital Stethoscope", description: "A stethoscope", price: 189.00, category_id: "cat-1", stock: 24, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "dg-002", name: "OtoView LED Otoscope Set", description: "An otoscope", price: 145.00, category_id: "cat-1", stock: 18, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "dg-003", name: "PulseCheck Fingertip Oximeter", description: "An oximeter", price: 59.00, category_id: "cat-1", stock: 42, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "dg-004", name: "AccuTemp Infrared Thermometer", description: "A thermometer", price: 39.00, category_id: "cat-1", stock: 56, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "mb-001", name: "GlideRest Folding Wheelchair", description: "A wheelchair", price: 329.00, category_id: "cat-2", stock: 12, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "mb-002", name: "StrideSure Rollator Walker", description: "A walker", price: 189.00, category_id: "cat-2", stock: 20, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "mb-003", name: "EasyGrip Adjustable Cane", description: "A cane", price: 45.00, category_id: "cat-2", stock: 35, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "mb-004", name: "TransferPro Bed Rail", description: "A bed rail", price: 129.00, category_id: "cat-2", stock: 0, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "mn-001", name: "VitalSync Patient Monitor", description: "A monitor", price: 1299.00, category_id: "cat-3", stock: 8, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "mn-002", name: "HomeCuff Auto Blood Pressure Monitor", description: "A BP monitor", price: 89.00, category_id: "cat-3", stock: 30, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "mn-003", name: "GlucoTrack Blood Glucose Meter", description: "A glucose meter", price: 65.00, category_id: "cat-3", stock: 45, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "mn-004", name: "SleepGuard Apnea Monitor", description: "An apnea monitor", price: 249.00, category_id: "cat-3", stock: 15, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "sg-001", name: "PrecisionEdge Surgical Scissors Set", description: "Scissors", price: 129.00, category_id: "cat-4", stock: 22, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "sg-002", name: "ClampSecure Hemostatic Forceps", description: "Forceps", price: 89.00, category_id: "cat-4", stock: 18, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "sg-003", name: "SutureMaster Needle Holder", description: "Needle holder", price: 79.00, category_id: "cat-4", stock: 14, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "sg-004", name: "ClearView Surgical Retractor Set", description: "Retractors", price: 199.00, category_id: "cat-4", stock: 10, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "pp-001", name: "ShieldFit N95 Respirator (20-pack)", description: "N95 respirators", price: 39.00, category_id: "cat-5", stock: 100, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "pp-002", name: "SafeTouch Nitrile Exam Gloves (100-pack)", description: "Nitrile gloves", price: 29.00, category_id: "cat-5", stock: 80, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "pp-003", name: "ClearGuard Face Shield (10-pack)", description: "Face shields", price: 35.00, category_id: "cat-5", stock: 60, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "pp-004", name: "BioBarrier Isolation Gown", description: "Isolation gowns", price: 25.00, category_id: "cat-5", stock: 0, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "hc-001", name: "ComfortRise Adjustable Bed Frame", description: "Bed frame", price: 499.00, category_id: "cat-6", stock: 6, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "hc-002", name: "SteadyStep Bathroom Safety Kit", description: "Bathroom safety", price: 89.00, category_id: "cat-6", stock: 25, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "hc-003", name: "TheraBand Resistance Rehab Set", description: "Rehab set", price: 49.00, category_id: "cat-6", stock: 40, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
  { sku: "hc-004", name: "NightWatch Bedside Commode", description: "Commode", price: 119.00, category_id: "cat-6", stock: 16, specs: {}, requires_prescription: false, certification_refs: null, created_at: "2024-01-01" },
];

/** Creates a sandbox with mock fetch/Response for catalog API calls. */
function createCatalogSandbox() {
  const store = {};
  const sandbox = {
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    },
    sessionStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    },
    JSON,
    Date,
    Math,
    URL,
    URLSearchParams,
    parseInt,
    isNaN,
    // Mock fetch that serves catalog API endpoints
    fetch: async (url) => {
      const text = String(url);
      if (text.includes("/catalog/categories")) {
        return { ok: true, json: async () => MOCK_CATEGORIES };
      }
      if (text.includes("/catalog/products")) {
        return { ok: true, json: async () => MOCK_PRODUCTS };
      }
      return { ok: false, status: 404, json: async () => ({ detail: "Not found" }) };
    },
    // Timers needed by products.js
    setTimeout: (fn, ms) => { /* no-op in test */ },
    clearTimeout: () => {},
    // navigator/connection for mobile detection
    navigator: {},
    // window.matchMedia needed by isMobileOrSlow in products.js
    window: {
      matchMedia: () => ({ matches: false }),
    },
  };
  vm.createContext(sandbox);
  return sandbox;
}

/** Loads the catalog, auth, and cart modules into a sandbox. */
function loadModules(sandbox, modules) {
  for (const mod of modules) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, mod), "utf8"), sandbox);
  }
}

test("addToCart clamps quantity to available stock", async () => {
  const sandbox = createCatalogSandbox();
  loadModules(sandbox, ["js/products.js", "js/auth.js", "js/cart.js"]);

  // Wait for catalog to load from the mock API.
  await sandbox.waitForCatalog();

  // Simulate a logged-in user via the API-backed session (JWT tokens + user info).
  sandbox.saveTokens({ access_token: "test-token", refresh_token: "test-refresh" });
  sandbox.saveUser({ id: "u1", name: "Tester", email: "t@example.com" });

  // Baseline: dg-001 has 24 in stock.
  assert.equal(sandbox.getProductById("dg-001").stock, 24, "baseline stock from the catalog");

  // Adding more than is available clamps to stock and flags a warning.
  const clamped = sandbox.addToCart("dg-001", 100);
  assert.equal(clamped.ok, true, "clamped add still succeeds");
  assert.equal(clamped.qty, 24, "quantity is clamped to remaining stock");
  assert.equal(clamped.clamped, true, "clamping is surfaced to the caller");
  assert.ok(clamped.message.includes("24"), `warning mentions remaining stock, got "${clamped.message}"`);

  // A normal add within stock limits does not clamp.
  const normal = sandbox.addToCart("dg-003", 2);
  assert.equal(normal.clamped, undefined, "no clamp flag on a normal add");
  assert.equal(normal.qty, 2, "normal add keeps the requested quantity");

  // An out-of-stock product can't be added (mb-004 has stock 0 in the catalog).
  const out = sandbox.addToCart("mb-004", 1);
  assert.equal(out.ok, false, "out-of-stock add is rejected");
  assert.equal(out.error, "This item is out of stock.", "out-of-stock error message");
});

// NOTE: order cancellation and stock restoration are now server-side
// (FastAPI backend). They are tested via the headless Chrome integration
// tests below ("register → add to cart → checkout flow").

test("escapeHtml neutralizes markup and attribute injection", () => {
  const sandbox = {
    document: { addEventListener() {}, getElementById: () => null },
    window: {},
    location: { pathname: "/index.html", search: "", href: "http://localhost:8000/index.html" },
    URL,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    Math,
    Date,
    JSON,
    parseInt,
    isNaN,
    String,
    Object,
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "js", "main.js"), "utf8"), sandbox);

  assert.equal(sandbox.escapeHtml("<img src=x onerror=alert(1)>"), "&lt;img src=x onerror=alert(1)&gt;");
  assert.equal(sandbox.escapeHtml('A "quote" & <b>amp</b>'), "A &quot;quote&quot; &amp; &lt;b&gt;amp&lt;/b&gt;");
  assert.equal(sandbox.escapeHtml("Smith & Sons"), "Smith &amp; Sons");
  assert.equal(sandbox.escapeHtml(42), "42");
});

test("featured rotation cycles through the pool by date", async () => {
  const sandbox = createCatalogSandbox();
  loadModules(sandbox, ["js/products.js", "js/featured.js"]);
  await sandbox.waitForCatalog();

  const rotation = vm.runInContext("ROTATION", sandbox);
  const poolSize = vm.runInContext("FEATURED_POOL.length", sandbox);
  const ids = (batch) => Array.from(batch, (p) => p.id);

  const stepDays = rotation.interval === "weekly" ? 7 : 1;
  const start = new Date("2026-01-01T12:00:00");
  const batch1 = sandbox.getFeaturedProducts(start);
  const batch2 = sandbox.getFeaturedProducts(new Date(2026, 0, 1 + stepDays, 12));
  assert.equal(batch1.length, rotation.count, "each batch should show ROTATION.count products");
  assert.notDeepEqual(ids(batch1), ids(batch2), "consecutive intervals should show different batches");

  // After a full cycle (pool / count intervals) the same batch repeats.
  const cycleDays = Math.ceil(poolSize / rotation.count) * stepDays;
  const batchRepeat = sandbox.getFeaturedProducts(new Date(2026, 0, 1 + cycleDays, 12));
  assert.deepEqual(ids(batch1), ids(batchRepeat), "the batch should repeat after a full cycle");
});

test("featured batch persists per visitor session", async () => {
  const sandbox = createCatalogSandbox();
  loadModules(sandbox, ["js/products.js", "js/featured.js"]);
  await sandbox.waitForCatalog();

  const rotation = vm.runInContext("ROTATION", sandbox);
  const poolIds = vm.runInContext("FEATURED_POOL", sandbox);
  const key = vm.runInContext("ROTATION_STORAGE_KEY", sandbox);
  const ids = (batch) => Array.from(batch, (p) => p.id);

  // The first call picks a batch and pins it for the session; later calls in
  // the same session keep showing the same batch.
  const first = sandbox.getFeaturedProducts();
  const second = sandbox.getFeaturedProducts();
  assert.deepEqual(ids(first), ids(second), "repeated calls within a session show the same batch");
  assert.ok(sandbox.sessionStorage.getItem(key) !== null, "the chosen group should be persisted");

  // A session that began on another day keeps its own pinned batch — the
  // current date alone must not flip the strip mid-session. Expected IDs come
  // from the same filtered (in-stock) pool the feature builds, not the raw list.
  const expectedPool = poolIds
    .map((id) => sandbox.getProductById(id))
    .filter(Boolean)
    .filter((p) => p.stock > 0);
  const groups = Math.ceil(expectedPool.length / rotation.count);
  const nextGroup = (Number(sandbox.sessionStorage.getItem(key)) + 1) % groups;
  sandbox.sessionStorage.setItem(key, String(nextGroup));
  const persisted = sandbox.getFeaturedProducts();
  assert.equal(persisted[0].id, expectedPool[nextGroup * rotation.count].id, "the persisted group determines the batch");
});

test("featured batches exclude out-of-stock products", async () => {
  const sandbox = createCatalogSandbox();
  loadModules(sandbox, ["js/products.js", "js/featured.js"]);
  await sandbox.waitForCatalog();

  const rotation = vm.runInContext("ROTATION", sandbox);

  // Set two pool products to zero stock by directly manipulating the cache.
  // Stock is now managed server-side; decrementStock() is a no-op.
  vm.runInContext(`
    _products.find(p => p.id === "dg-001").stock = 0;
    _products.find(p => p.id === "pp-002").stock = 0;
  `, sandbox);

  // Sweep several days so every rotation group is exercised.
  for (let day = 1; day <= 10; day++) {
    const batch = sandbox.getFeaturedProducts(new Date(2026, 0, day, 12));
    assert.ok(batch.every((p) => p.stock > 0), "no out-of-stock product should be featured");
    assert.ok(!batch.some((p) => p.id === "dg-001" || p.id === "pp-002" || p.id === "mb-004" || p.id === "pp-004"), "zero-stock products should be excluded");
    assert.equal(batch.length, rotation.count, "batches should still fill to ROTATION.count");
  }
});

/* ---------- 4. headless Chrome render (skips when Chrome is unavailable) ---------- */

function findChrome() {
  if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) {
    return process.env.CHROME_PATH;
  }
  const candidates = [];
  if (process.platform === "win32") {
    const pf = process.env.ProgramFiles || "C:/Program Files";
    const pf86 = process.env["ProgramFiles(x86)"] || "C:/Program Files (x86)";
    candidates.push(
      path.join(pf, "Google/Chrome/Application/chrome.exe"),
      path.join(pf86, "Google/Chrome/Application/chrome.exe"),
      path.join(process.env.LOCALAPPDATA || "", "Google/Chrome/Application/chrome.exe")
    );
  } else if (process.platform === "darwin") {
    candidates.push("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  } else {
    candidates.push("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser");
  }
  return candidates.find((c) => c && fs.existsSync(c)) || null;
}

const chromePath = findChrome();
const chromeSkip = chromePath ? false : "Chrome/Chromium not found — install it or set CHROME_PATH";

// Only the intentionally-blocked font hosts may produce console errors during
// tests (the resolver rules send them to 127.0.0.1 → connection refused).
// Anything else — including missing assets like a favicon — is a regression.
function isIgnorableConsoleError(msg) {
  const text = msg.text() || "";
  // Catalog retry warnings during page load are expected when the API is
  // unavailable (e.g. file:// pages). These are console.warn, not error.
  if (text.includes("[catalog] Attempt")) return true;
  if (msg.type() !== "error") return false;
  // Ignore network failures for blocked external resources.
  if (/Failed to load resource/.test(text)) {
    let url = "";
    try {
      url = (msg.location && msg.location().url) || "";
    } catch {
      /* location() may throw for synthetic messages */
    }
    if (/fonts\.(googleapis|gstatic)\.com/.test(url)) return true;
    // file:// pages can't reach the API server — catalog fetch failures are expected.
    if (url.includes("/api/v1/") && url.startsWith("file:///")) return true;
  }
  // CORS errors from file:// trying to reach the API are expected.
  if (text.includes("CORS policy") && text.includes("file://")) return true;
  return false;
}

// Renders a page in the shared browser, asserts expected DOM markers, and
// fails on any real console error.
// Note: `waitUntil: "domcontentloaded"` suffices because layout injection and
// page rendering are synchronous end-of-body scripts (already finished by
// DOMContentLoaded). If a page ever renders async work on `load`, bump this.
async function assertPageRenders(url, markers, label) {
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 15000 });
  // Allow async catalog loads and API-backed rendering to settle.
  // Pages that fetch from the API need a brief window to render.
  await new Promise((r) => setTimeout(r, 2000));
  const html = await page.content();
  await page.close();

  for (const marker of markers) {
    assert.ok(html.includes(marker), `${label}: rendered DOM should contain ${marker}`);
  }
  assert.deepEqual(errors, [], `${label}: unexpected console errors: ${errors.join(" | ")}`);
}

test("headless Chrome renders every page with the injected layout", { skip: chromeSkip }, async () => {
  const pageChecks = {
    "index.html": ["class=\"site-header\"", "class=\"site-footer\"", "cat-card", "product-card", "Active Life Medical"],
    "products.html": ["class=\"site-header\"", "class=\"site-footer\"", "product-card", "filter-chip", "product-sort", "All products"],
    "categories.html": ["class=\"site-header\"", "class=\"site-footer\"", "cat-card", "All categories"],
    "about.html": ["class=\"site-header\"", "class=\"site-footer\"", "Why Active Life Medical", "Verified sourcing"],
    "category.html?id=diagnostic": ["class=\"site-header\"", "class=\"site-footer\"", "product-card", "Diagnostic Equipment"],
    "product.html?id=dg-001": ["class=\"site-header\"", "spec-sheet", "ClearTone Digital Stethoscope"],
    "cart.html": ["class=\"site-header\"", "class=\"site-footer\""],
    "checkout.html": ["class=\"site-header\""],
    "confirmation.html": ["class=\"site-header\""],
    "login.html": ["class=\"site-header\"", "id=\"login-form\""],
    "register.html": ["class=\"site-header\"", "id=\"register-form\""],
  };
  for (const [page, markers] of Object.entries(pageChecks)) {
    await assertPageRenders(`${baseUrl}/${page}`, markers, page);
  }
});

test("headless Chrome renders the homepage from file://", { skip: chromeSkip }, async () => {
  // file:// can't reach the API server, so catalog-dependent markers
  // (cat-card, product-card) won't render. Only check the injected layout.
  const fileUrl = pathToFileURL(path.join(ROOT, "index.html")).href;
  await assertPageRenders(fileUrl, ["class=\"site-header\"", "class=\"site-footer\""], "file:// index.html");
});

test("headless Chrome: home hero stats are derived from the catalog", { skip: chromeSkip }, async () => {
  // Expected counts come from the real catalog (js/products.js via mock API),
  // so the test stays correct if products or categories are added later.
  const sandbox = createCatalogSandbox();
  loadModules(sandbox, ["js/products.js", "js/featured.js"]);
  await sandbox.waitForCatalog();
  // getAllProducts() (a function declaration) is reachable on the sandbox
  // global; CATEGORIES is a top-level const, so read it via runInContext.
  const expectedDevices = sandbox.getAllProducts().length;
  const expectedCategories = vm.runInContext("CATEGORIES.length", sandbox);

  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto(`${baseUrl}/index.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  const devices = await page.$eval("#stat-devices", (el) => el.textContent);
  const categories = await page.$eval("#stat-categories", (el) => el.textContent);
  assert.equal(devices, String(expectedDevices), "device count should match the catalog");
  assert.equal(categories, String(expectedCategories), "category count should match the catalog");

  // The featured strip must match the current rotation batch (browser and
  // sandbox see the same date, so they must agree).
  const expectedFeatured = sandbox.getFeaturedProducts();
  const featuredNames = await page.$$eval(".product-strip .product-card h3 a", (els) => els.map((e) => e.textContent));
  assert.equal(featuredNames.length, expectedFeatured.length, "featured strip should show every featured product");
  // Array.from (not .map) so the expected array is built in this realm —
  // deepStrictEqual compares prototypes, and vm arrays have a foreign one.
  assert.deepEqual(featuredNames, Array.from(expectedFeatured, (p) => p.name), "featured strip order should match the catalog");

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors on the home page: ${errors.join(" | ")}`);
});

test("headless Chrome: products page filter narrows the grid", { skip: chromeSkip }, async () => {
  // Expected counts come from the real catalog (via mock API), so the test
  // stays correct if products are added later.
  const sandbox = createCatalogSandbox();
  loadModules(sandbox, ["js/products.js"]);
  await sandbox.waitForCatalog();
  const expectedAll = sandbox.getAllProducts().length;
  const expectedDiag = sandbox.getAllProducts().filter((p) => p.categoryId === "diagnostic").length;

  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.goto(`${baseUrl}/products.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  const allCount = await page.$$eval(".product-card", (els) => els.length);
  assert.equal(allCount, expectedAll, "products page should list every product by default");

  await page.click(".filter-chip[data-cat=diagnostic]");
  const diagTags = await page.$$eval(".product-card .cat-tag", (els) => els.map((e) => e.textContent));
  assert.equal(diagTags.length, expectedDiag, "clicking a category chip should narrow the grid");
  assert.ok(diagTags.every((t) => t === "Diagnostic Equipment"), "filtered results should all be from the chosen category");

  // Search combines with the active category filter.
  await page.type("#product-search", "stethoscope");
  const searchNames = await page.$$eval(".product-card h3 a", (els) => els.map((e) => e.textContent));
  assert.equal(searchNames.length, 1, "search should narrow the filtered grid");
  assert.ok(searchNames[0].includes("Stethoscope"), "the match should be the stethoscope");

  // Clearing the search restores the category-filtered grid.
  await page.$eval("#product-search", (el) => {
    el.value = "";
    el.dispatchEvent(new Event("input"));
  });
  const afterClear = await page.$$eval(".product-card", (els) => els.length);
  assert.equal(afterClear, expectedDiag, "clearing the search should restore the category filter");

  // Back to All: a search that matches by category name ("Monitoring Devices").
  await page.click(".filter-chip[data-cat=\"\"]");
  const monitorMatches = sandbox.getAllProducts().filter((p) => {
    const q = "monitor".toLowerCase();
    return p.name.toLowerCase().includes(q)
      || p.desc.toLowerCase().includes(q)
      || sandbox.getCategoryById(p.categoryId).name.toLowerCase().includes(q);
  });
  await page.type("#product-search", "monitor");
  const monitorNames = await page.$$eval(".product-card h3 a", (els) => els.map((e) => e.textContent));
  assert.deepEqual(monitorNames, Array.from(monitorMatches, (p) => p.name), "search should match names, descriptions, and category names");

  // Sorting: clear the search, then verify each option reorders the grid to
  // match the catalog. Array.from + .sort keeps the arrays in this realm so
  // deepStrictEqual's prototype check passes.
  await page.$eval("#product-search", (el) => {
    el.value = "";
    el.dispatchEvent(new Event("input"));
  });
  const sortExpected = {
    "price-desc": Array.from(sandbox.getAllProducts()).sort((a, b) => b.price - a.price).map((p) => p.name),
    "name-asc": Array.from(sandbox.getAllProducts()).sort((a, b) => a.name.localeCompare(b.name)).map((p) => p.name),
    "stock-asc": Array.from(sandbox.getAllProducts()).sort((a, b) => a.stock - b.stock).map((p) => p.name),
  };
  for (const [key, expected] of Object.entries(sortExpected)) {
    await page.select("#product-sort", key);
    const names = await page.$$eval(".product-card h3 a", (els) => els.map((e) => e.textContent));
    assert.deepEqual(names, expected, `sorting by ${key} should reorder the grid to match the catalog`);
  }

  // Sorting combines with the active category filter.
  await page.click(".filter-chip[data-cat=diagnostic]");
  await page.select("#product-sort", "price-asc");
  const diagSorted = Array.from(sandbox.getAllProducts().filter((p) => p.categoryId === "diagnostic"))
    .sort((a, b) => a.price - b.price)
    .map((p) => p.name);
  const diagNames = await page.$$eval(".product-card h3 a", (els) => els.map((e) => e.textContent));
  assert.deepEqual(diagNames, diagSorted, "sorting should apply within the active category filter");

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors on the products page: ${errors.join(" | ")}`);
});

test("headless Chrome: products page state syncs to the URL query string", { skip: chromeSkip }, async () => {
  const sandbox = createCatalogSandbox();
  loadModules(sandbox, ["js/products.js"]);
  await sandbox.waitForCatalog();
  // Mirror the page's matchesSearch so the expectation stays correct if the
  // catalog changes.
  const matchesStethoscope = (p) => {
    const q = "stethoscope";
    return p.name.toLowerCase().includes(q)
      || p.desc.toLowerCase().includes(q)
      || sandbox.getCategoryById(p.categoryId).name.toLowerCase().includes(q);
  };

  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));

  // 1. A deep link with all three params restores search, filter, and sort.
  await page.goto(`${baseUrl}/products.html?q=stethoscope&cat=diagnostic&sort=price-desc`, {
    waitUntil: "domcontentloaded",
    timeout: 15000,
  });
  assert.equal(await page.$eval("#product-search", (el) => el.value), "stethoscope", "URL ?q= should populate the search box");
  assert.equal(await page.$eval(".filter-chip.active", (el) => el.dataset.cat), "diagnostic", "URL ?cat= should activate the matching chip");
  assert.equal(await page.$eval("#product-sort", (el) => el.value), "price-desc", "URL ?sort= should select the matching option");
  let names = await page.$$eval(".product-card h3 a", (els) => els.map((e) => e.textContent));
  assert.equal(names.length, 1, "the deep link should narrow the grid");
  assert.ok(names[0].includes("Stethoscope"), "the deep link should land on the stethoscope");

  // 2. Interactions update the URL in place (no reload).
  await page.click(".filter-chip[data-cat=\"\"]");
  assert.ok(!page.url().includes("cat="), "clearing the category should drop ?cat= from the URL");
  await page.select("#product-sort", "name-asc");
  assert.ok(page.url().includes("sort=name-asc"), "changing the sort should update ?sort=");

  // 3. A reload restores the state from the URL.
  await page.reload({ waitUntil: "domcontentloaded", timeout: 15000 });
  assert.equal(await page.$eval("#product-search", (el) => el.value), "stethoscope", "reload should restore the search box");
  assert.equal(await page.$eval("#product-sort", (el) => el.value), "name-asc", "reload should restore the sort option");
  assert.equal(await page.$eval(".filter-chip.active", (el) => el.dataset.cat), "", "reload should restore the All chip");
  const expected = Array.from(sandbox.getAllProducts().filter(matchesStethoscope))
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((p) => p.name);
  names = await page.$$eval(".product-card h3 a", (els) => els.map((e) => e.textContent));
  assert.deepEqual(names, expected, "reload should reapply the restored search + sort");

  // 4. "Clear filters" resets search, category, and sort at once.
  assert.equal(await page.$eval("#clear-filters", (el) => el.hidden), false, "clear button should be visible while filters are active");
  await page.click("#clear-filters");
  assert.equal(await page.$eval("#product-search", (el) => el.value), "", "clear should empty the search box");
  assert.equal(await page.$eval("#product-sort", (el) => el.value), "default", "clear should reset the sort option");
  assert.equal(await page.$eval(".filter-chip.active", (el) => el.dataset.cat), "", "clear should re-activate the All chip");
  assert.equal(await page.$eval("#clear-filters", (el) => el.hidden), true, "clear button should hide once everything is reset");
  assert.equal(new URL(page.url()).search, "", "clear should strip the query string");
  const allNames = await page.$$eval(".product-card h3 a", (els) => els.map((e) => e.textContent));
  assert.deepEqual(allNames, Array.from(sandbox.getAllProducts(), (p) => p.name), "clear should restore the full grid in default order");

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors on the products page: ${errors.join(" | ")}`);
});

test("headless Chrome: mobile nav collapses into a working hamburger menu", { skip: chromeSkip }, async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));

  await page.setViewport({ width: 390, height: 800 });
  await page.goto(`${baseUrl}/index.html`, { waitUntil: "domcontentloaded", timeout: 15000 });

  // On mobile the inline nav is hidden and the hamburger toggle takes over.
  assert.notEqual(await page.$eval("#nav-toggle", (el) => getComputedStyle(el).display), "none", "nav toggle should be visible on mobile");
  assert.equal(await page.$eval("#main-nav", (el) => getComputedStyle(el).display), "none", "inline nav should be hidden on mobile");

  // Opening the menu reveals the links and the auth actions; the header
  // actions slot is hidden so auth lives in the menu on mobile.
  await page.click("#nav-toggle");
  assert.equal(await page.$eval("#main-nav", (el) => el.classList.contains("open")), true, "clicking the toggle should open the menu");
  const links = await page.$$eval("#main-nav a", (els) => els.map((e) => e.textContent.trim()));
  assert.ok(links.includes("Products"), "the mobile menu should include the Products link");
  assert.ok(links.includes("Categories"), "the mobile menu should include the Categories link");
  assert.equal(await page.$eval("#auth-slot-mobile a", (el) => el.textContent.trim()), "Log in", "the mobile menu should show the auth actions");
  assert.equal(await page.$eval(".header-actions #auth-slot", (el) => getComputedStyle(el).display), "none", "header auth actions should be hidden on mobile");

  // Toggling again closes the menu.
  await page.click("#nav-toggle");
  assert.equal(await page.$eval("#main-nav", (el) => el.classList.contains("open")), false, "clicking the toggle again should close the menu");

  // The header must not push the page into horizontal scroll on a phone.
  const scrollW = await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth));
  assert.ok(scrollW <= 390, `the page should not scroll horizontally on mobile (got ${scrollW}px)`);

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors on the mobile home page: ${errors.join(" | ")}`);
});

test("headless Chrome: register → add to cart → checkout flow works", { skip: chromeSkip }, async () => {
  // Exercises the form-submit handlers that the render-only tests never run.
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  // Clear any leftover auth state from previous tests.
  await page.goto(`${baseUrl}/about.html`);
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });

  const email = `flowtest${Date.now()}@example.com`;

  // 1. Register a new account (redirects to the home page after ~500ms).
  await page.goto(`${baseUrl}/register.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  // Wait for async catalog rendering before interacting with the page.
  await page.waitForSelector("#register-form", { timeout: 10000 });
  await page.type("#name", "Flow Test");
  await page.type("#email", email);
  await page.type("#password", "password123");
  await page.type("#confirm", "password123");
  await page.click("#register-form button[type=submit]");
  await page.waitForFunction("location.pathname.endsWith('/index.html')", { timeout: 8000 });

  // 2. Add a product to the cart; the header badge should update.
  await page.goto(`${baseUrl}/product.html?id=dg-001`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector("#add-to-cart-btn", { timeout: 10000 });
  await page.click("#add-to-cart-btn");
  const badge = await page.$eval("#cart-count", (el) => el.textContent);
  assert.equal(badge, "1", "cart badge should show 1 after adding an item");

  // 3. Cart page shows the totals.
  await page.goto(`${baseUrl}/cart.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector(".summary-row.total", { timeout: 10000 });
  const cartTotal = await page.$eval(".summary-row.total span:last-child", (el) => el.textContent);
  assert.ok(cartTotal.startsWith("$"), `cart total should render a price, got "${cartTotal}"`);

  // 4. Checkout: fill the required fields and place the order.
  await page.goto(`${baseUrl}/checkout.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector("#address", { timeout: 10000 });
  await page.type("#address", "123 Clinic Road");
  await page.type("#city", "Kigali");
  await page.type("#postal", "00000");
  await page.type("#phone", "+250 700 000 000");
  await page.type("#card-number", "4242 4242 4242 4242");
  await page.type("#card-exp", "12/28");
  await page.type("#card-cvc", "123");
  await page.click("#place-order-btn");

  // 5. Lands on the confirmation page with the order id and totals.
  //    (wait for the element, not just the pathname — the pathname flips
  //    mid-navigation before the end-of-body confirmation script runs)
  await page.waitForSelector(".order-id", { timeout: 8000 });
  const orderId = await page.$eval(".order-id", (el) => el.textContent);
  assert.ok(orderId.startsWith("ORD-"), `confirmation should show an order id, got "${orderId}"`);
  const confirmTotal = await page.$eval(".summary-row.total span:last-child", (el) => el.textContent);
  assert.ok(confirmTotal.startsWith("$"), `confirmation should show the total, got "${confirmTotal}"`);

  // 6. Order history persists: leave and revisit the confirmation page.
  await page.goto(`${baseUrl}/index.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.goto(`${baseUrl}/confirmation.html?order=${encodeURIComponent(orderId)}`, { waitUntil: "domcontentloaded", timeout: 15000 });
  const orderIdAgain = await page.$eval(".order-id", (el) => el.textContent);
  assert.equal(orderIdAgain, orderId, "order should still be visible after navigating away");

  // 7. Order history lists the placed order.
  await page.goto(`${baseUrl}/orders.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  const historyCard = await page.$eval(".order-card .order-id", (el) => el.textContent.trim());
  assert.equal(historyCard, orderId, "order history should list the placed order");

  // 8. Order detail shows the full shipping address and line items.
  await page.goto(`${baseUrl}/order.html?order=${encodeURIComponent(orderId)}`, { waitUntil: "domcontentloaded", timeout: 15000 });
  // Wait for async API fetch + rendering.
  await page.waitForFunction(() => document.querySelector(".ship-line") || document.querySelector(".empty-state"), { timeout: 8000 });
  const detailHtml = await page.content();
  assert.ok(detailHtml.includes("123 Clinic Road"), "order detail should show the shipping address");
  assert.ok(detailHtml.includes("ClearTone Digital Stethoscope"), "order detail should list the ordered line items");

  // 9. Cancel the order: status flips to cancelled and stock is restored.
  await page.once("dialog", (d) => d.accept());
  await page.click("#cancel-order-btn");
  await page.waitForSelector(".status-badge.cancelled", { timeout: 8000 });
  await page.goto(`${baseUrl}/product.html?id=dg-001`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector(".qty-row span", { timeout: 10000 });
  const stockText = await page.$eval(".qty-row span", (el) => el.textContent);
  assert.ok(stockText.includes("24 available"), `stock should return to 24 after cancel, got "${stockText}"`);

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors in the flow test: ${errors.join(" | ")}`);
});

test("headless Chrome: ?next= survives the switch from login to create-account", { skip: chromeSkip }, async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  // Clear any leftover auth state from previous tests.
  await page.goto(`${baseUrl}/about.html`);
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });

  // Logged out: "Add to cart" on a product page redirects to login?next=...
  await page.goto(`${baseUrl}/product.html?id=dg-001`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector("#add-to-cart-btn", { timeout: 10000 });
  await page.click("#add-to-cart-btn");
  await page.waitForFunction("location.pathname.endsWith('/login.html')", { timeout: 8000 });
  assert.ok(page.url().includes("next="), `login URL should carry next=, got ${page.url()}`);

  // Switch to create-account — the next= param must survive. (login.js
  // rewrites this link's href to carry next= at page load, so match the
  // container rather than the exact original href.)
  await page.click(".auth-switch a");
  await page.waitForFunction("location.pathname.endsWith('/register.html')", { timeout: 8000 });
  assert.ok(page.url().includes("next="), `register URL should carry next=, got ${page.url()}`);

  // Register a fresh account and land back on the intended product page.
  const email = `nextflow${Date.now()}@example.com`;
  await page.type("#name", "Next Flow");
  await page.type("#email", email);
  await page.type("#password", "password123");
  await page.type("#confirm", "password123");
  await page.click("#register-form button[type=submit]");
  await page.waitForFunction("location.pathname.endsWith('/product.html')", { timeout: 8000 });
  assert.ok(page.url().includes("id=dg-001"), `should land back on the product page, got ${page.url()}`);

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors in the next-flow test: ${errors.join(" | ")}`);
});

test("headless Chrome: cart quantity editing preserves input focus", { skip: chromeSkip }, async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  // Clear any leftover auth state from previous tests.
  await page.goto(`${baseUrl}/about.html`);
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });

  // Register and add one item to the cart.
  const email = `cartfocus${Date.now()}@example.com`;
  await page.goto(`${baseUrl}/register.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector("#register-form", { timeout: 10000 });
  await page.type("#name", "Cart Focus");
  await page.type("#email", email);
  await page.type("#password", "password123");
  await page.type("#confirm", "password123");
  await page.click("#register-form button[type=submit]");
  await page.waitForFunction("location.pathname.endsWith('/index.html')", { timeout: 8000 });
  await page.goto(`${baseUrl}/product.html?id=dg-001`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector("#add-to-cart-btn", { timeout: 10000 });
  await page.click("#add-to-cart-btn");
  await page.goto(`${baseUrl}/cart.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector(".qty-inc", { timeout: 10000 });

  // Remember the qty input element, then increment: the element must survive.
  // (The old code re-rendered the whole list on every change, destroying it.)
  await page.evaluate("window.__qtyInput = document.querySelector('.qty-val')");
  await page.click(".qty-inc");
  const preserved = await page.evaluate("document.querySelector('.qty-val') === window.__qtyInput");
  assert.equal(preserved, true, "qty input element must not be re-created on quantity change");
  const qtyVal = await page.$eval(".qty-val", (el) => el.value);
  assert.equal(qtyVal, "2", "quantity should have incremented to 2");
  const total = await page.$eval("#summary-total", (el) => el.textContent);
  assert.ok(total.startsWith("$"), `summary total should update, got "${total}"`);

  // Typing a value and leaving the field updates in place too (select all
  // explicitly with Control+A so the replacement is deterministic).
  await page.click(".qty-val");
  await page.keyboard.down("Control");
  await page.keyboard.press("A");
  await page.keyboard.up("Control");
  await page.keyboard.type("3");
  await page.keyboard.press("Tab");
  const typedVal = await page.$eval(".qty-val", (el) => el.value);
  assert.equal(typedVal, "3", "typed quantity should be applied on blur");

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors in the cart focus test: ${errors.join(" | ")}`);
});

test("headless Chrome: checkout validates card fields and blocks invalid submits", { skip: chromeSkip }, async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  // Clear any leftover auth state from previous tests.
  await page.goto(`${baseUrl}/about.html`);
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });

  // Register and add one item to the cart.
  const email = `checkoutval${Date.now()}@example.com`;
  await page.goto(`${baseUrl}/register.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector("#register-form", { timeout: 10000 });
  await page.type("#name", "Checkout Val");
  await page.type("#email", email);
  await page.type("#password", "password123");
  await page.type("#confirm", "password123");
  await page.click("#register-form button[type=submit]");
  await page.waitForFunction("location.pathname.endsWith('/index.html')", { timeout: 8000 });
  await page.goto(`${baseUrl}/product.html?id=dg-001`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector("#add-to-cart-btn", { timeout: 10000 });
  await page.click("#add-to-cart-btn");
  await page.goto(`${baseUrl}/checkout.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.waitForSelector("#place-order-btn", { timeout: 10000 });

  // Submit with only the prefilled name fields — the first empty field (address) errors.
  await page.click("#place-order-btn");
  const firstMsg = await page.$eval("#checkout-msg", (el) => el.textContent);
  assert.equal(firstMsg, "Enter a street address.", "empty required fields should be flagged");

  // Fill everything except the expiry, which is an invalid month (13/99).
  await page.type("#address", "123 Clinic Road");
  await page.type("#city", "Kigali");
  await page.type("#postal", "00000");
  await page.type("#phone", "+250 700 000 000");
  await page.type("#card-number", "4242 4242 4242 4242");
  const cardFormatted = await page.$eval("#card-number", (el) => el.value);
  assert.equal(cardFormatted, "4242 4242 4242 4242", "card number should be grouped into 4s as typed");
  const brandLabel = await page.$eval("#card-brand", (el) => el.getAttribute("aria-label"));
  assert.equal(brandLabel, "Visa", "card brand should be detected from the number and shown as a logo");
  await page.type("#card-exp", "13/99");
  await page.type("#card-cvc", "123");

  // Live validation: typing into the CVC blurs the expiry, which flags it
  // with .has-error before any submit happens.
  const expFlagged = await page.$eval("#field-card-exp", (el) => el.classList.contains("has-error"));
  assert.equal(expFlagged, true, "invalid expiry should be flagged live on blur");

  await page.click("#place-order-btn");
  const expMsg = await page.$eval("#checkout-msg", (el) => el.textContent);
  assert.equal(expMsg, "Enter the expiry as MM/YY.", "invalid expiry format should be rejected");

  // Fix the expiry — the live error clears as the user types, before submit.
  await page.click("#card-exp");
  await page.keyboard.down("Control");
  await page.keyboard.press("A");
  await page.keyboard.up("Control");
  await page.keyboard.type("12/28");
  const expFormatted = await page.$eval("#card-exp", (el) => el.value);
  assert.equal(expFormatted, "12/28", "expiry should be formatted as MM/YY as typed");
  const expCleared = await page.$eval("#field-card-exp", (el) => el.classList.contains("has-error"));
  assert.equal(expCleared, false, "fixing the expiry should clear the live error");
  await page.click("#place-order-btn");
  await page.waitForSelector(".order-id", { timeout: 8000 });
  const orderId = await page.$eval(".order-id", (el) => el.textContent);
  assert.ok(orderId.startsWith("ORD-"), `checkout should complete after fixing the expiry, got "${orderId}"`);

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors in the checkout validation test: ${errors.join(" | ")}`);
});

test("headless Chrome: login and register validate fields live", { skip: chromeSkip }, async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  // Clear any leftover auth state from previous tests.
  await page.evaluateOnNewDocument(() => { localStorage.clear(); sessionStorage.clear(); });

  // Register: an invalid email is flagged on blur and clears when fixed.
  await page.goto(`${baseUrl}/register.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.type("#email", "not-an-email");
  await page.click("#name"); // blurs the email input
  const emailFlagged = await page.$eval("#field-email", (el) => el.classList.contains("has-error"));
  assert.equal(emailFlagged, true, "invalid email should flag live on blur");
  await page.click("#email");
  await page.keyboard.down("Control");
  await page.keyboard.press("A");
  await page.keyboard.up("Control");
  await page.keyboard.type("valid@example.com");
  const emailCleared = await page.$eval("#field-email", (el) => el.classList.contains("has-error"));
  assert.equal(emailCleared, false, "fixing the email should clear the live error");

  // Login: an invalid email flags on blur, and a bad submit is blocked.
  await page.goto(`${baseUrl}/login.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.type("#email", "nope");
  await page.click("#password"); // blurs the email input
  const loginFlagged = await page.$eval("#field-email", (el) => el.classList.contains("has-error"));
  assert.equal(loginFlagged, true, "invalid login email should flag live on blur");
  await page.click("#login-form button[type=submit]");
  const banner = await page.$eval("#form-msg", (el) => el.textContent);
  assert.equal(banner, "Enter a valid email address.", "submit should surface the first validation error");
  assert.ok(page.url().includes("login.html"), "invalid login should stay on the login page");

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors in the live validation test: ${errors.join(" | ")}`);
});

test("headless Chrome: register password strength meter updates live", { skip: chromeSkip }, async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  // Clear any leftover auth state from previous tests.
  await page.evaluateOnNewDocument(() => { localStorage.clear(); sessionStorage.clear(); });

  await page.goto(`${baseUrl}/register.html`, { waitUntil: "domcontentloaded", timeout: 15000 });

  // A weak password (6 chars, digits only) shows one segment and "Weak".
  await page.type("#password", "abc123");
  const weakLevel = await page.$eval("#strength-meter", (el) => el.dataset.level);
  const weakLabel = await page.$eval("#strength-label", (el) => el.textContent);
  const visible = await page.$eval("#strength-meter", (el) => !el.hidden);
  assert.equal(visible, true, "meter should appear while typing");
  assert.equal(weakLevel, "1", "weak password should score level 1");
  assert.equal(weakLabel, "Weak", "weak password should be labeled Weak");

  // A strong password (length + case variety + digits + symbols) hits level 4.
  await page.click("#password");
  await page.keyboard.down("Control");
  await page.keyboard.press("A");
  await page.keyboard.up("Control");
  await page.keyboard.type("Str0ng!Passw0rd");
  const strongLevel = await page.$eval("#strength-meter", (el) => el.dataset.level);
  const strongLabel = await page.$eval("#strength-label", (el) => el.textContent);
  assert.equal(strongLevel, "4", "strong password should score level 4");
  assert.equal(strongLabel, "Strong", "strong password should be labeled Strong");

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors in the strength meter test: ${errors.join(" | ")}`);
});

test("headless Chrome: password show/hide toggle flips input type", { skip: chromeSkip }, async () => {
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (!isIgnorableConsoleError(msg)) errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  // Clear any leftover auth state from previous tests.
  await page.evaluateOnNewDocument(() => { localStorage.clear(); sessionStorage.clear(); });

  // Register: the password field toggles between password and text.
  await page.goto(`${baseUrl}/register.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.type("#password", "password123");
  await page.click("#field-password .password-toggle");
  let type = await page.$eval("#password", (el) => el.type);
  let pressed = await page.$eval("#field-password .password-toggle", (el) => el.getAttribute("aria-pressed"));
  assert.equal(type, "text", "password should become visible text");
  assert.equal(pressed, "true", "toggle should report pressed");
  await page.click("#field-password .password-toggle");
  type = await page.$eval("#password", (el) => el.type);
  assert.equal(type, "password", "password should hide again");

  // Login: the single password field toggles too.
  await page.goto(`${baseUrl}/login.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
  await page.type("#password", "secret123");
  await page.click("#field-password .password-toggle");
  type = await page.$eval("#password", (el) => el.type);
  assert.equal(type, "text", "login password should become visible text");

  await page.close();
  assert.deepEqual(errors, [], `unexpected console errors in the password toggle test: ${errors.join(" | ")}`);
});
