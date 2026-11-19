/* ============================================================
   Active Life Medical — Category page: renders a category's products and
   wires the "Add to cart" buttons.
   ============================================================ */

/* global waitForCatalog, catalogLoadFailed, catalogErrorMessage, CATALOG_LOADING_HTML, catalogErrorHTML, retryCatalog, getCategoryById, getProductsByCategory, stockLabel, formatPrice, addToCart, redirectToLogin, showToast, renderCartBadge */

const params = new URLSearchParams(location.search);
const catId = params.get("id");
const grid = document.getElementById("product-grid");
const headerEl = document.getElementById("cat-header");

// Show loading state immediately
grid.innerHTML = CATALOG_LOADING_HTML;

waitForCatalog().then(() => {
  const category = getCategoryById(catId);

  if (catalogLoadFailed()) {
    headerEl.innerHTML = `<h1>Category not found</h1>`;
    grid.innerHTML = catalogErrorHTML(catalogErrorMessage(), retryCatalog);
    return;
  }

  if (!category) {
    headerEl.innerHTML = `<h1>Category not found</h1><p style="color:var(--color-text-muted);">Try browsing all categories instead.</p><a class="btn btn-primary" href="categories.html">Back to categories</a>`;
    grid.innerHTML = "";
    return;
  }

  document.title = `${category.name} — Active Life Medical`;
  document.getElementById("crumb-current").textContent = category.name;
  headerEl.innerHTML = `
    <span class="eyebrow">Category</span>
    <h1>${category.name}</h1>
    <p style="color:var(--color-text-muted); max-width:60ch;">${category.tagline}</p>
  `;

  const products = getProductsByCategory(catId);
  grid.innerHTML = products.map(p => {
    const stock = stockLabel(p.stock);
    return `
      <div class="product-card">
        <a href="product.html?id=${p.id}" class="product-thumb">
          <span class="stock-badge ${stock.cls}">${stock.text}</span>
          ${p.icon || category.icon}
        </a>
        <div class="product-body">
          <span class="cat-tag">${category.name}</span>
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
  }).join("") || `<p style="color:var(--color-text-muted);">No products found in this category yet.</p>`;

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
      if (result.clamped) {
        showToast(result.message, "info");
      } else {
        showToast("Added to cart.", "success");
      }
    });
  });
});
