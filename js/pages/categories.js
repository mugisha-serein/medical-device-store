/* ============================================================
   Active Life Medical — Categories page: renders the full category grid.
   ============================================================ */

/* global CATEGORIES, waitForCatalog, catalogLoadFailed, catalogErrorMessage, CATALOG_LOADING_HTML, catalogErrorHTML, retryCatalog, getProductsByCategory */

const grid = document.getElementById("category-grid");

// Show loading state immediately
grid.innerHTML = CATALOG_LOADING_HTML;

waitForCatalog().then(() => {

  if (catalogLoadFailed()) {
    grid.innerHTML = catalogErrorHTML(catalogErrorMessage(), retryCatalog);
    return;
  }

  grid.innerHTML = CATEGORIES.map(cat => `
    <a class="cat-card" href="category.html?id=${cat.id}">
      <div class="cat-icon">${cat.icon}</div>
      <h3>${cat.name}</h3>
      <p class="count">${getProductsByCategory(cat.id).length} products</p>
      <p style="font-size:0.85rem; color:var(--color-text-muted); margin:0;">${cat.tagline}</p>
      <span class="cat-link">Browse →</span>
    </a>
  `).join("");

});
