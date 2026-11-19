/* ============================================================
   Active Life Medical — Order confirmation page: shows a single order
   (the one just placed) fetched from the API.
   ============================================================ */

/* global isLoggedIn, redirectToLogin, formatPrice, escapeHtml, authFetch, API_BASE */

const root = document.getElementById("confirmation-root");

if (!isLoggedIn()) {
  redirectToLogin("Please log in to view your order.");
} else {
  const params = new URLSearchParams(location.search);
  const orderId = params.get("order");

  if (!orderId) {
    document.title = "Order not found — Active Life Medical";
    root.innerHTML = `
      <div class="empty-state" style="max-width:560px; margin:40px auto;">
        <h3>Order not found</h3>
        <p style="color:var(--color-text-muted);">No order ID was provided.</p>
        <a class="btn btn-primary" href="categories.html">Browse categories</a>
      </div>
    `;
  } else {
    // Fetch order from API
    authFetch(`${API_BASE}/orders/${encodeURIComponent(orderId)}`)
      .then(response => {
        if (!response.ok) {
          throw new Error("not found");
        }
        return response.json();
      })
      .then(order => {
        document.title = `Order ${order.id} — Active Life Medical`;
        const placed = new Date(order.placed_at).toLocaleString();

        root.innerHTML = `
          <div class="confirm-wrap">
            <svg class="confirm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-6"/></svg>
            <h1>Order confirmed</h1>
            <p style="color:var(--color-text-muted);">Thanks — your order has been received and is being prepared for dispatch.</p>
            <div class="order-id mono">${escapeHtml(order.id)}</div>
            <p class="mono" style="color:var(--color-text-muted); font-size:0.78rem; margin:0 0 26px;">Placed ${escapeHtml(placed)}</p>
            <div class="summary-card" style="text-align:left; max-width:420px; margin:0 auto 28px;">
              <h3>Order summary</h3>
              <div class="order-review-list" style="max-height:200px;">
                ${order.items.map(l => `
                  <div class="order-review-line"><span class="name">${escapeHtml(l.product_name)}</span><span class="qty">×${escapeHtml(String(l.quantity))} — $${formatPrice(l.line_total)}</span></div>
                `).join("")}
              </div>
              <div class="summary-row"><span>Subtotal</span><span>$${formatPrice(order.subtotal)}</span></div>
              <div class="summary-row"><span>Shipping</span><span>${order.shipping_cost === 0 ? "Free" : "$" + formatPrice(order.shipping_cost)}</span></div>
              <div class="summary-row total"><span>Total paid</span><span>$${formatPrice(order.total)}</span></div>
            </div>
            <div class="confirm-actions">
              <a class="btn btn-outline" href="order.html?order=${encodeURIComponent(order.id)}">View full details</a>
              <a class="btn btn-primary" href="categories.html">Continue shopping</a>
            </div>
          </div>
        `;
      })
      .catch(() => {
        document.title = "Order not found — Active Life Medical";
        root.innerHTML = `
          <div class="empty-state" style="max-width:560px; margin:40px auto;">
            <h3>Order not found</h3>
            <p style="color:var(--color-text-muted);">We couldn't find that order on this account.</p>
            <a class="btn btn-primary" href="categories.html">Browse categories</a>
          </div>
        `;
      });
  }
}
