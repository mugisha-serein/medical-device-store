/* ============================================================
   Active Life Medical — Cart page: renders cart lines with quantity
   editing and the order summary.
   ============================================================ */

/* global isLoggedIn, waitForCatalog, catalogLoadFailed, catalogErrorMessage, CATALOG_LOADING_HTML, catalogErrorHTML, retryCatalog, getCartDetailed, formatPrice, getCategoryById, getProductById, updateCartQty, renderCartBadge, removeFromCart, showToast */

const root = document.getElementById("cart-root");

function updateSummary() {
  const { subtotal, shipping, total } = getCartDetailed();
  document.getElementById("summary-subtotal").textContent = `$${formatPrice(subtotal)}`;
  document.getElementById("summary-shipping").textContent = shipping === 0 ? "Free" : `$${formatPrice(shipping)}`;
  document.getElementById("summary-total").textContent = `$${formatPrice(total)}`;
}

function updateLineQty(id, qty) {
  const lineEl = document.querySelector(`.cart-line[data-id="${id}"]`);
  if (!lineEl) return;
  const stored = updateCartQty(id, qty);
  const product = getProductById(id);
  lineEl.querySelector(".qty-val").value = stored;
  lineEl.querySelector(".line-price").textContent = `$${formatPrice(product ? product.price * stored : 0)}`;
  updateSummary();
  renderCartBadge();
}

function renderCartPage() {
  if (!isLoggedIn()) {
    root.innerHTML = `
      <div class="empty-state">
        <svg class="vitals-line" viewBox="0 0 200 60" xmlns="http://www.w3.org/2000/svg">
          <polyline points="0,30 30,30 40,10 50,50 60,20 70,30 130,30 140,15 150,45 160,30 200,30" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <h3>Log in to view your cart</h3>
        <p>Your cart is tied to your account so it's there whenever you come back.</p>
        <a class="btn btn-primary" href="login.html?next=cart.html">Log in</a>
      </div>
    `;
    return;
  }

  const { lines, subtotal, shipping, total } = getCartDetailed();

  if (lines.length === 0) {
    root.innerHTML = `
      <div class="empty-state">
        <svg class="vitals-line" viewBox="0 0 200 60" xmlns="http://www.w3.org/2000/svg">
          <polyline points="0,30 30,30 40,10 50,50 60,20 70,30 130,30 140,15 150,45 160,30 200,30" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <h3>Your cart is empty</h3>
        <p>Browse our categories to find the equipment you need.</p>
        <a class="btn btn-primary" href="categories.html">Browse categories</a>
      </div>
    `;
    return;
  }

  root.innerHTML = `
    <div class="cart-layout">
      <div class="cart-items" id="cart-items"></div>
      <div class="summary-card">
        <h3>Order summary</h3>
        <div class="summary-row"><span>Subtotal</span><span id="summary-subtotal">$${formatPrice(subtotal)}</span></div>
        <div class="summary-row"><span>Shipping</span><span id="summary-shipping">${shipping === 0 ? "Free" : "$" + formatPrice(shipping)}</span></div>
        <div class="summary-row total"><span>Total</span><span id="summary-total">$${formatPrice(total)}</span></div>
        <a href="checkout.html" class="btn btn-primary btn-block" style="margin-top:16px;">Proceed to checkout</a>
        <a href="categories.html" class="btn btn-ghost btn-block" style="margin-top:6px;">Continue shopping</a>
      </div>
    </div>
  `;

  const itemsEl = document.getElementById("cart-items");
  itemsEl.innerHTML = lines.map(l => {
    const cat = getCategoryById(l.product.categoryId);
    return `
      <div class="cart-line" data-id="${l.productId}">
        <div class="thumb">${l.product.icon || (cat && cat.icon)}</div>
        <div>
          <span class="cat-tag">${cat ? cat.name : ""}</span>
          <h4><a href="product.html?id=${l.productId}" style="color:inherit;">${l.product.name}</a></h4>
          <div class="qty-control">
            <button type="button" class="qty-dec" aria-label="Decrease quantity">−</button>
            <input type="text" class="qty-val" value="${l.qty}" inputmode="numeric" aria-label="Quantity">
            <button type="button" class="qty-inc" aria-label="Increase quantity">+</button>
          </div>
        </div>
        <div class="line-price">$${formatPrice(l.lineTotal)}</div>
        <button class="remove-btn" type="button">Remove</button>
      </div>
    `;
  }).join("");

  itemsEl.querySelectorAll(".cart-line").forEach(lineEl => {
    const id = lineEl.dataset.id;
    const input = lineEl.querySelector(".qty-val");

    lineEl.querySelector(".qty-dec").addEventListener("click", () => {
      const cur = parseInt(input.value, 10);
      updateLineQty(id, Math.max(1, (isNaN(cur) ? 1 : cur) - 1));
    });
    lineEl.querySelector(".qty-inc").addEventListener("click", () => {
      const cur = parseInt(input.value, 10);
      updateLineQty(id, (isNaN(cur) ? 1 : cur) + 1);
    });
    input.addEventListener("change", () => {
      let v = parseInt(input.value, 10);
      if (isNaN(v) || v < 1) v = 1;
      updateLineQty(id, v);
    });
    lineEl.querySelector(".remove-btn").addEventListener("click", () => {
      removeFromCart(id);
      lineEl.remove();
      if (getCartDetailed().lines.length === 0) {
        renderCartPage();
      } else {
        updateSummary();
      }
      renderCartBadge();
      showToast("Item removed from cart.", "info");
    });
  });
}

// Show loading state while catalog loads (cart needs product data)
root.innerHTML = CATALOG_LOADING_HTML;

waitForCatalog().then(() => {
  if (catalogLoadFailed()) {
    root.innerHTML = catalogErrorHTML(catalogErrorMessage(), retryCatalog);
    return;
  }
  renderCartPage();
});
