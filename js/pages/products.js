/* ============================================================
   Active Life Medical — Products page: every product in the catalog, with
   category filter chips, search, sorting, and add-to-cart
   buttons. The search/filter/sort state lives in the URL
   query string, so it survives reloads and can be shared.
   ============================================================ */

/* global CATEGORIES, waitForCatalog, catalogLoadFailed, catalogErrorMessage, CATALOG_LOADING_HTML, catalogErrorHTML, retryCatalog, getCategoryById, getAllProducts, stockLabel, formatPrice, addToCart, redirectToLogin, showToast, renderCartBadge */

const searchInput = document.getElementById("product-search");
const sortSelect = document.getElementById("product-sort");
const clearBtn = document.getElementById("clear-filters");
const filterRow = document.getElementById("filter-row");
const grid = document.getElementById("product-grid");

const SORT_KEYS = ["default", "price-asc", "price-desc", "name-asc", "name-desc", "stock-desc", "stock-asc"];

let activeCategory = null;
let searchQuery = "";
let sortKey = "default";

// Show loading state immediately
filterRow.innerHTML = "";
grid.innerHTML = CATALOG_LOADING_HTML;

function initFromUrl() {
  const params = new URLSearchParams(location.search);
  const q = params.get("q");
  if (q) {
    searchQuery = q.trim();
    searchInput.value = searchQuery;
  }
  const cat = params.get("cat");
  if (cat && CATEGORIES.some && CATEGORIES.some(c => c.id === cat)) {
    activeCategory = cat;
  }
  const sort = params.get("sort");
  if (SORT_KEYS.includes(sort)) {
    sortKey = sort;
    sortSelect.value = sort;
  }
}

function syncUrl() {
  const params = new URLSearchParams();
  if (searchQuery) params.set("q", searchQuery);
  if (activeCategory) params.set("cat", activeCategory);
  if (sortKey !== "default") params.set("sort", sortKey);
  const qs = params.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

function hasActiveFilters() {
  return Boolean(searchQuery) || activeCategory !== null || sortKey !== "default";
}

function updateClearButton() {
  clearBtn.hidden = !hasActiveFilters();
}

function matchesSearch(p) {
  if (!searchQuery) return true;
  const q = searchQuery.toLowerCase();
  const cat = getCategoryById(p.categoryId);
  return p.name.toLowerCase().includes(q)
    || p.desc.toLowerCase().includes(q)
    || (cat && cat.name.toLowerCase().includes(q));
}

function applySort(list) {
  const sorted = [...list];
  switch (sortKey) {
    case "price-asc": sorted.sort((a, b) => a.price - b.price); break;
    case "price-desc": sorted.sort((a, b) => b.price - a.price); break;
    case "name-asc": sorted.sort((a, b) => a.name.localeCompare(b.name)); break;
    case "name-desc": sorted.sort((a, b) => b.name.localeCompare(a.name)); break;
    case "stock-desc": sorted.sort((a, b) => b.stock - a.stock); break;
    case "stock-asc": sorted.sort((a, b) => a.stock - b.stock); break;
  }
  return sorted;
}

function productCard(p) {
  const category = getCategoryById(p.categoryId);
  const stock = stockLabel(p.stock);
  return `
    <div class="product-card">
      <a href="product.html?id=${p.id}" class="product-thumb">
        <span class="stock-badge ${stock.cls}">${stock.text}</span>
        ${p.icon || (category && category.icon)}
      </a>
      <div class="product-body">
        <span class="cat-tag">${category ? category.name : ""}</span>
        <h3><a href="product.html?id=${p.id}" style="color:inherit;">${p.name}</a></h3>
        <p class="desc">${p.desc}</p>
        <div class="product-footer">
          <div class="price"><span class="cur">USD</span>$${formatPrice(p.price)}</div>
          <button class="btn btn-outline btn-sm add-btn" data-id="${p.id}" ${p.stock <= 0 ? "disabled" : ""}>
            ${p.stock <= 0 ? "Unavailable" : "Add to cart"}
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderGrid() {
  const products = applySort(
    getAllProducts()
      .filter(p => !activeCategory || p.categoryId === activeCategory)
      .filter(matchesSearch)
  );
  grid.innerHTML = products.map(productCard).join("") ||
    `<p style="color:var(--color-text-muted);">No products match your filters.</p>`;

  grid.querySelectorAll(".add-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      const result = addToCart(id, 1);
      if (!result.ok && result.authRequired) {
        redirectToLogin("Please log in to add items to your cart.");
        return;
      }
      if (!result.ok) {
        showToast(result.error, "error");
        return;
      }
      renderCartBadge();
      showToast(result.clamped ? result.message : "Added to cart.", result.clamped ? "info" : "success");
    });
  });
}

function renderFilters() {
  filterRow.innerHTML = `
    <button type="button" class="filter-chip ${activeCategory === null ? "active" : ""}" data-cat="">All</button>
    ${CATEGORIES.map(cat => `
      <button type="button" class="filter-chip ${activeCategory === cat.id ? "active" : ""}" data-cat="${cat.id}">${cat.name}</button>
    `).join("")}
  `;
  filterRow.querySelectorAll(".filter-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      activeCategory = chip.dataset.cat || null;
      renderFilters();
      renderGrid();
      syncUrl();
      updateClearButton();
    });
  });
}

searchInput.addEventListener("input", () => {
  searchQuery = searchInput.value.trim();
  renderGrid();
  syncUrl();
  updateClearButton();
});

sortSelect.addEventListener("change", () => {
  sortKey = sortSelect.value;
  renderGrid();
  syncUrl();
  updateClearButton();
});

clearBtn.addEventListener("click", () => {
  searchQuery = "";
  searchInput.value = "";
  activeCategory = null;
  sortKey = "default";
  sortSelect.value = "default";
  renderFilters();
  renderGrid();
  syncUrl();
  updateClearButton();
});

waitForCatalog().then(() => {
  if (catalogLoadFailed()) {
    filterRow.innerHTML = "";     grid.innerHTML = catalogErrorHTML(catalogErrorMessage(), retryCatalog);
    return;
  }

  initFromUrl();
  renderFilters();
  renderGrid();
  updateClearButton();
});
