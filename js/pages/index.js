/* ============================================================
   Active Life Medical — Home page: hero stats, featured products strip,
   and a featured categories preview. The full category grid
   lives on categories.html.
   ============================================================ */

/* global CATEGORIES, waitForCatalog, catalogLoadFailed, catalogErrorMessage, CATALOG_LOADING_HTML, catalogErrorHTML, retryCatalog, getAllProducts, getProductsByCategory, getCategoryById, getFeaturedProducts, stockLabel, formatPrice, addToCart, redirectToLogin, showToast, renderCartBadge */

const strip = document.getElementById("featured-strip");
const grid = document.getElementById("category-grid");

// Show loading state immediately
strip.innerHTML = CATALOG_LOADING_HTML;
grid.innerHTML = CATALOG_LOADING_HTML;

waitForCatalog().then(() => {

  if (catalogLoadFailed()) {
    strip.innerHTML = "";
    grid.innerHTML = catalogErrorHTML(catalogErrorMessage(), retryCatalog);
    return;
  }

  // Hero stats are derived from the catalog so they always match
  // js/products.js — no hardcoded counts to drift out of date.
  document.getElementById("stat-devices").textContent = getAllProducts().length;
  document.getElementById("stat-categories").textContent = CATEGORIES.length;

  /* ---- featured products strip ---- */

  strip.innerHTML = getFeaturedProducts().map(p => {
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
  }).join("");

  strip.querySelectorAll(".add-btn").forEach(btn => {
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

  /* ---- featured categories preview ---- */

  grid.innerHTML = CATEGORIES.slice(0, 3).map(cat => `
    <a class="cat-card" href="category.html?id=${cat.id}">
      <div class="cat-icon">${cat.icon}</div>
      <h3>${cat.name}</h3>
      <p class="count">${getProductsByCategory(cat.id).length} products</p>
      <p style="font-size:0.85rem; color:var(--color-text-muted); margin:0;">${cat.tagline}</p>
      <span class="cat-link">Browse →</span>
    </a>
  `).join("");

});
