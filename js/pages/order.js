/* ============================================================
   Active Life Medical — Order detail page: shows one order's shipping
   address, line items, and totals, fetched from the API.
   ============================================================ */

/* global isLoggedIn, redirectToLogin, formatPrice, escapeHtml, showToast, authFetch, API_BASE */

const root = document.getElementById("order-root");

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
        <a class="btn btn-primary" href="orders.html">Back to order history</a>
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
          <div class="order-detail-wrap">
            <div class="order-detail-head">
              <div>
                <span class="eyebrow">Order details</span>
                <h1>Order ${escapeHtml(order.id)}<span class="status-badge ${order.status === "cancelled" ? "cancelled" : "placed"}">${order.status === "cancelled" ? "Cancelled" : "Placed"}</span></h1>
                <p class="mono" style="color:var(--color-text-muted); font-size:0.8rem; margin:6px 0 0;">Placed ${escapeHtml(placed)}</p>
              </div>
              <a class="btn btn-outline btn-sm" href="orders.html">← Back to order history</a>
            </div>

            <div class="order-detail-grid">
              <div class="summary-card detail-card">
                <h3>Shipping address</h3>
                ${order.shipping_name ? `
                  <div class="shipping-block">
                    <div class="ship-line"><span class="label">Name</span><span>${escapeHtml(order.shipping_name)}</span></div>
                    <div class="ship-line"><span class="label">Address</span><span>${escapeHtml(order.shipping_address || "")}</span></div>
                    <div class="ship-line"><span class="label">City</span><span>${escapeHtml(order.shipping_city || "")}${order.shipping_postal ? `, ${escapeHtml(order.shipping_postal)}` : ""}</span></div>
                    <div class="ship-line"><span class="label">Phone</span><span>${escapeHtml(order.shipping_phone || "")}</span></div>
                  </div>
                ` : `
                  <p style="color:var(--color-text-muted); font-size:0.85rem; margin:0;">Shipping details were not recorded for this order.</p>
                `}
              </div>

              <div class="summary-card detail-card">
                <h3>Items</h3>
                <div class="order-review-list">
                  ${order.items.map(l => `
                    <div class="order-review-line">
                      <span class="name"><a href="product.html?id=${encodeURIComponent(l.product_id)}" style="color:inherit;">${escapeHtml(l.product_name)}</a></span>
                      <span class="qty">×${escapeHtml(String(l.quantity))} — $${formatPrice(l.line_total)}</span>
                    </div>
                  `).join("")}
                </div>
                <div class="summary-row"><span>Subtotal</span><span>$${formatPrice(order.subtotal)}</span></div>
                <div class="summary-row"><span>Shipping</span><span>${order.shipping_cost === 0 ? "Free" : "$" + formatPrice(order.shipping_cost)}</span></div>
                <div class="summary-row total"><span>Total paid</span><span>$${formatPrice(order.total)}</span></div>
              </div>
            </div>

            <div class="order-actions">
              ${order.status === "cancelled"
                ? ""
                : `<button type="button" class="btn btn-danger" id="cancel-order-btn">Cancel order — return items to stock</button>`}
            </div>
          </div>
        `;

        // Wire up cancel button
        const cancelBtn = document.getElementById("cancel-order-btn");
        if (cancelBtn) {
          cancelBtn.addEventListener("click", async () => {
            if (!window.confirm("Cancel this order? The items will be returned to stock.")) return;

            try {
              const response = await authFetch(`${API_BASE}/orders/${encodeURIComponent(order.id)}/cancel`, {
                method: "POST",
              });

              if (!response.ok) {
                const data = await response.json();
                throw new Error(data.detail || "Failed to cancel order.");
              }

              showToast("Order cancelled — items returned to stock.", "success");
              location.reload();
            } catch (err) {
              showToast(err.message || "Failed to cancel order.", "error");
            }
          });
        }
      })
      .catch(() => {
        document.title = "Order not found — Active Life Medical";
        root.innerHTML = `
          <div class="empty-state" style="max-width:560px; margin:40px auto;">
            <h3>Order not found</h3>
            <p style="color:var(--color-text-muted);">We couldn't find that order on this account.</p>
            <a class="btn btn-primary" href="orders.html">Back to order history</a>
          </div>
        `;
      });
  }
}
