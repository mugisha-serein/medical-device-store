/* ============================================================
   Active Life Medical — Product & Category Data (API-backed)
   Fetches catalog data from the FastAPI backend and caches it.
   All accessor functions read from the local cache.
   Call waitForCatalog() before using any catalog data.
   ============================================================ */

/* exported CATEGORIES, getCategoryById, getProductById, getProductsByCategory,
   getAllProducts, decrementStock, incrementStock, stockLabel, formatPrice,
   waitForCatalog, catalogLoadFailed, catalogErrorMessage,
   CATALOG_LOADING_HTML, catalogErrorHTML */

/* API base is resolved at runtime: same-origin first (production / docker /
   proxied dev server), then local FastAPI on common ports as a fallback.
   Other scripts read this global via `API_BASE`. */
let API_BASE = "/api/v1";

const API_FALLBACK_ORIGINS = ["http://localhost:8001", "http://localhost:8000"];

async function resolveApiBase() {
  // 1. Same-origin API (FastAPI serving the frontend, or proxied dev server)
  try {
    const res = await fetch("/api/v1/health");
    if (res.ok) return "/api/v1";
  } catch { /* not available on this origin */ }

  // 2. Fallback: local FastAPI on common ports (CORS is permissive in dev)
  for (const origin of API_FALLBACK_ORIGINS) {
    if (origin === window.location.origin) continue;
    try {
      const res = await fetch(`${origin}/api/v1/health`);
      if (res.ok) return `${origin}/api/v1`;
    } catch { /* try next */ }
  }

  return "/api/v1"; // give up — let the normal request/report flow handle it
}

/* ---- category icons (fallback when API doesn't supply SVGs) ---- */
const CATEGORY_ICONS = {
  diagnostic: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="22" cy="16" r="6"/><path d="M22 22v14a12 12 0 0 0 24 0v-6"/><path d="M46 30a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"/><path d="M14 36v4a8 8 0 0 0 8 8"/></svg>`,
  mobility: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="24" cy="42" r="14"/><circle cx="52" cy="50" r="5"/><path d="M24 42h16l10 8"/><path d="M24 28h10l6 14"/><path d="M18 14h12"/><path d="M24 14v10"/></svg>`,
  monitoring: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="10" y="14" width="44" height="30" rx="4"/><path d="M16 30h6l4-9 6 18 4-13 3 4h9"/><path d="M22 50h20"/></svg>`,
  surgical: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 14l24 24"/><circle cx="12" cy="12" r="4"/><path d="M50 14 26 38"/><circle cx="52" cy="12" r="4"/><path d="M26 38l-8 8a5 5 0 1 0 6 6l8-8"/></svg>`,
  ppe: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 26c8-6 14-9 22-9s14 3 22 9"/><path d="M10 26c0 10 8 16 22 16s22-6 22-16"/><path d="M20 30c4 3 8 4 12 4s8-1 12-4"/></svg>`,
  homecare: `<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 30 32 12l22 18"/><path d="M16 28v22h32V28"/><path d="M26 50v-12h12v12"/></svg>`
};

/* ---- retry config ---- */
const BASE_RETRY_DELAY_MS = 1500; // base delay for exponential backoff

/** Detect mobile / slow connection via network heuristic or viewport. */
function isMobileOrSlow() {
  // Network Information API (Chrome, Edge, some Android browsers)
  const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (conn) {
    // effectiveType: 'slow-2g', '2g', '3g', '4g'
    if (conn.effectiveType && /slow-2g|2g|3g/.test(conn.effectiveType)) return true;
    if (conn.saveData) return true;
  }
  // Fallback: narrow viewport likely means mobile
  if (window.matchMedia && window.matchMedia("(max-width: 768px)").matches) return true;
  return false;
}

const MAX_RETRIES = isMobileOrSlow() ? 2 : 1;

/* ---- in-memory cache ---- */
let _categories = [];   // array of { id, slug, name, tagline, icon }
let _products = [];     // array of { id, categoryId, name, desc, price, stock, specs, icon, ... }
let _catalogReady = false;
let _catalogError = null; // null on success, Error on failure
let _catalogPromise = null;
let _retryCount = 0;

/* ---- fetch helpers ---- */

async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

/**
 * Fetches categories and products from the API and populates the cache.
 * Maps backend fields to frontend conventions:
 *   - product.id        = sku (e.g. "dg-001")
 *   - product.categoryId = category slug (e.g. "diagnostic")
 *   - product.desc       = description
 *   - category.id        = slug
 *   - category.icon      = icon_svg or built-in fallback
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

let _apiBaseResolved = false;

async function loadCatalog(attempt = 0) {
  try {
    if (!_apiBaseResolved) {
      API_BASE = await resolveApiBase();
      _apiBaseResolved = true;
    }
    const [apiCategories, apiProducts] = await Promise.all([
      fetchJSON(`${API_BASE}/catalog/categories`),
      fetchJSON(`${API_BASE}/catalog/products?limit=200`),
    ]);

    // Build category map: slug -> frontend category object
    _categories = apiCategories.map(c => ({
      id: c.slug,
      slug: c.slug,
      name: c.name,
      tagline: c.tagline || "",
      icon: c.icon_svg || CATEGORY_ICONS[c.slug] || "",
    }));

    // Build products array in frontend format
    _products = apiProducts.map(p => {
      // Find the category by matching category_id (UUID) to the API category list
      const apiCat = apiCategories.find(c => c.id === p.category_id);
      const catSlug = apiCat ? apiCat.slug : "";

      return {
        id: p.sku,
        categoryId: catSlug,
        name: p.name,
        desc: p.description || "",
        price: p.price,
        stock: p.stock,
        specs: p.specs || {},
        requires_prescription: p.requires_prescription || false,
        certification_refs: p.certification_refs || null,
        icon: CATEGORY_ICONS[catSlug] || "",
        createdAt: p.created_at,
      };
    });

    _catalogReady = true;
  } catch (err) {
    if (attempt < MAX_RETRIES) {
      const delay = BASE_RETRY_DELAY_MS * Math.pow(2, attempt); // 1.5s, 3s, 6s…
      console.warn(`[catalog] Attempt ${attempt + 1}/${MAX_RETRIES + 1} failed, retrying in ${delay}ms…`, err.message);
      await sleep(delay);
      return loadCatalog(attempt + 1);
    }
    console.error("[catalog] All retry attempts exhausted:", err);
    _catalogError = err;
    _catalogReady = true; // still mark as ready so waitForCatalog resolves
  }
}

/**
 * Returns a promise that resolves when the catalog data is loaded.
 * Safe to call multiple times — returns the same promise.
 */
function waitForCatalog() {
  if (!_catalogPromise) {
    _catalogPromise = loadCatalog(0);
  }
  return _catalogPromise;
}

/** Returns true if the catalog load failed. */
function catalogLoadFailed() {
  return _catalogError !== null;
}

/** Returns the error message if load failed, or null. */
function catalogErrorMessage() {
  if (!_catalogError) return null;
  if (_catalogError.message && _catalogError.message.includes("HTTP")) {
    return "Unable to reach the server. Please check your connection and try again.";
  }
  return "Something went wrong loading the catalog. Please try again later.";
}

/* ---- accessor functions (read from cache) ---- */

/** Expose CATEGORIES as a getter for backward compatibility. */
const CATEGORIES = new Proxy([], {
  get(target, prop) {
    if (typeof prop === "string" && /^\d+$/.test(prop)) {
      return _categories[Number(prop)];
    }
    if (prop === "length") return _categories.length;
    if (prop === "map") return _categories.map.bind(_categories);
    if (prop === "filter") return _categories.filter.bind(_categories);
    if (prop === "slice") return _categories.slice.bind(_categories);
    if (prop === "find") return _categories.find.bind(_categories);
    if (prop === "some") return _categories.some.bind(_categories);
    if (prop === "forEach") return _categories.forEach.bind(_categories);
    if (prop === Symbol.iterator) return _categories[Symbol.iterator].bind(_categories);
    return target[prop];
  }
});

function getCategoryById(id) {
  return _categories.find(c => c.id === id) || null;
}

function findProduct(id) {
  return _products.find(p => p.id === id) || null;
}

function getProductById(id) {
  const product = findProduct(id);
  if (!product) return null;
  return { ...product };
}

function getProductsByCategory(categoryId) {
  return _products
    .filter(p => p.categoryId === categoryId)
    .map(p => ({ ...p }));
}

function getAllProducts() {
  return _products.map(p => ({ ...p }));
}

/* ---- stock helpers (now server-side; these are no-ops kept for compat) ---- */

function decrementStock(productId, qty) {
  // Stock is managed server-side. This is kept for backward compatibility
  // but is now a no-op — the server decrements on order placement.
}

function incrementStock(productId, qty) {
  // Stock is managed server-side. This is kept for backward compatibility.
}

/* ---- pure utility functions ---- */

function stockLabel(stock) {
  if (stock <= 0) return { text: "Out of stock", cls: "out" };
  if (stock <= 10) return { text: "Low stock", cls: "low" };
  return { text: "In stock", cls: "" };
}

function formatPrice(n) {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ---- reusable HTML helpers for loading/error states ---- */

const CATALOG_LOADING_HTML = `
  <div class="catalog-loading">
    <div class="spinner">
      <svg viewBox="0 0 200 60" xmlns="http://www.w3.org/2000/svg">
        <polyline points="0,30 30,30 40,10 50,50 60,20 70,30 130,30 140,15 150,45 160,30 200,30" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <p class="spinner-label">Loading catalog…</p>
  </div>
`;

function catalogErrorHTML(message, retryFn) {
  const id = "catalog-retry-" + Math.random().toString(36).slice(2, 8);
  // Defer wiring the retry button until after insertion into the DOM
  setTimeout(() => {
    const btn = document.getElementById(id);
    if (btn && retryFn) btn.addEventListener("click", retryFn);
  }, 0);
  return `
    <div class="catalog-error">
      <div class="error-icon">!</div>
      <h3>Unable to load catalog</h3>
      <p>${escapeHtmlStr(message)}</p>
      <button class="btn btn-outline retry-btn" id="${id}">Try again</button>
    </div>
  `;
}

function escapeHtmlStr(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* ---- auto-start loading ---- */
waitForCatalog();

/**
 * Retry catalog fetch (called from manual "Try again" buttons).
 * Resets state and re-runs the load with retries.
 */
function retryCatalog() {
  _catalogReady = false;
  _catalogError = null;
  _catalogPromise = null;
  _retryCount = 0;
  waitForCatalog();
}
