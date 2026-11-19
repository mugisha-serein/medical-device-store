/* ============================================================
   Active Life Medical — Product detail page: renders the spec sheet,
   quantity control, and add-to-cart / buy-now actions.
   ============================================================ */

/* global waitForCatalog, catalogLoadFailed, catalogErrorMessage, CATALOG_LOADING_HTML, catalogErrorHTML, retryCatalog, getProductById, getCategoryById, stockLabel, formatPrice, isLoggedIn, addToCart, redirectToLogin, showToast, renderCartBadge */

const params = new URLSearchParams(location.search);
const productId = params.get("id");
const root = document.getElementById("product-root");
const crumb = document.getElementById("breadcrumb");

// Show loading state immediately
root.innerHTML = CATALOG_LOADING_HTML;

waitForCatalog().then(() => {
  const product = getProductById(productId);

  if (catalogLoadFailed()) {
    crumb.innerHTML = `<a href="index.html">Home</a>`;
    root.innerHTML = catalogErrorHTML(catalogErrorMessage(), retryCatalog);
    return;
  }

  if (!product) {
    crumb.innerHTML = `<a href="index.html">Home</a>`;
    root.innerHTML = `<div style="padding:60px 0;"><h1>Product not found</h1><p style="color:var(--color-text-muted);">This item may no longer be listed.</p><a class="btn btn-primary" href="categories.html">Back to shop</a></div>`;
    return;
  }

  const category = getCategoryById(product.categoryId);
  document.title = `${product.name} — Active Life Medical`;

  crumb.innerHTML = `
    <a href="index.html">Home</a><span class="sep">/</span>
    <a href="category.html?id=${category ? category.id : ""}">${category ? category.name : ""}</a><span class="sep">/</span>
    <span>${product.name}</span>
  `;

  const stock = stockLabel(product.stock);
  const specRows = Object.entries(product.specs).map(([label, val]) => `
    <div class="spec-row"><span class="label">${label}</span><span class="val">${val}</span></div>
  `).join("");

  root.innerHTML = `
    <div class="product-detail">
      <div class="detail-visual">${product.icon || (category && category.icon)}</div>
      <div class="detail-info">
        <span class="cat-tag">${category ? category.name : ""}</span>
        <h1>${product.name}</h1>
        <div class="sku">SKU: ${product.id.toUpperCase()} · <span class="mono">${stock.text}${product.stock > 0 ? ` (${product.stock} units)` : ""}</span></div>
        <div class="price-lg">$${formatPrice(product.price)}</div>
        <p class="desc">${product.desc}</p>

        <div class="qty-row">
          <div class="qty-control">
            <button type="button" id="qty-minus" aria-label="Decrease quantity">−</button>
            <input type="text" id="qty-input" value="1" inputmode="numeric" aria-label="Quantity">
            <button type="button" id="qty-plus" aria-label="Increase quantity">+</button>
          </div>
          <span style="color:var(--color-text-muted); font-size:0.85rem;">${product.stock > 0 ? `${product.stock} available` : "Currently unavailable"}</span>
        </div>

        <div class="detail-actions">
          <button class="btn btn-primary" id="add-to-cart-btn" ${product.stock <= 0 ? "disabled" : ""}>
            ${product.stock <= 0 ? "Out of stock" : "Add to cart"}
          </button>
          <button class="btn btn-outline" id="buy-now-btn" ${product.stock <= 0 ? "disabled" : ""}>Buy now</button>
        </div>

        ${!isLoggedIn() ? `<div class="notice-banner">🔒 You'll need to log in to add this item to your cart.</div>` : ""}

        <div class="spec-sheet">
          <h3>Specification sheet</h3>
          ${specRows}
        </div>
      </div>
    </div>
  `;

  const qtyInput = document.getElementById("qty-input");

  function readQty() {
    const v = parseInt(qtyInput.value, 10);
    if (isNaN(v) || v < 1) return 1;
    return Math.min(v, product.stock);
  }

  document.getElementById("qty-minus").addEventListener("click", () => {
    qtyInput.value = Math.max(1, readQty() - 1);
  });
  document.getElementById("qty-plus").addEventListener("click", () => {
    qtyInput.value = Math.min(product.stock, readQty() + 1);
  });
  qtyInput.addEventListener("change", () => {
    qtyInput.value = readQty();
  });

  function attemptAddToCart() {
    const qty = readQty();
    const result = addToCart(product.id, qty);
    if (!result.ok && result.authRequired) {
      redirectToLogin("Please log in to add items to your cart.");
      return null;
    }
    if (!result.ok) {
      showToast(result.error, "error");
      return null;
    }
    renderCartBadge();
    return result;
  }

  document.getElementById("add-to-cart-btn").addEventListener("click", () => {
    const result = attemptAddToCart();
    if (!result) return;
    if (result.clamped) {
      showToast(result.message, "info");
    } else {
      showToast("Added to cart.", "success");
    }
  });

  document.getElementById("buy-now-btn").addEventListener("click", () => {
    if (!isLoggedIn()) {
      redirectToLogin("Please log in to continue to checkout.");
      return;
    }
    if (attemptAddToCart()) {
      location.href = "checkout.html";
    }
  });
});
