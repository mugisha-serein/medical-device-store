/* ============================================================
   Active Life Medical — Order history page: lists the current user's
   past orders (newest first), fetched from the API.
   ============================================================ */

/* global isLoggedIn, redirectToLogin, fetchOrderHistory, formatPrice, escapeHtml */

const root = document.getElementById("orders-root");

if (!isLoggedIn()) {
  redirectToLogin("Please log in to view your order history.");
} else {
  // Fetch orders from API
  fetchOrderHistory()
    .then(result => {
      if (!result.ok) {
        root.innerHTML = `
          <div class="empty-state">
            <h3>Could not load orders</h3>
            <p style="color:var(--color-text-muted);">${escapeHtml(result.error)}</p>
            <a class="btn btn-primary" href="categories.html">Browse categories</a>
          </div>
        `;
        return;
      }

      const orders = result.orders;

      if (orders.length === 0) {
        root.innerHTML = `
          <div class="empty-state">
            <svg class="vitals-line" viewBox="0 0 200 60" xmlns="http://www.w3.org/2000/svg">
              <polyline points="0,30 30,30 40,10 50,50 60,20 70,30 130,30 140,15 150,45 160,30 200,30" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <h3>No orders yet</h3>
            <p>When you place an order, it will show up here with its full summary.</p>
            <a class="btn btn-primary" href="categories.html">Browse categories</a>
          </div>
        `;
      } else {
        root.innerHTML = `
          <div class="order-list">
            ${orders.map(order => {
              const placed = new Date(order.placed_at).toLocaleString();
              const itemCount = order.items.reduce((sum, l) => sum + l.quantity, 0);
              return `
          <div class="order-card">
            <div class="order-main">
              <div class="order-id mono">${escapeHtml(order.id)}</div>
              ${order.status === "cancelled" ? `<span class="status-badge cancelled">Cancelled</span>` : ""}
              <p class="order-placed">Placed ${escapeHtml(placed)}</p>
              <p class="order-lines">${itemCount} item${itemCount === 1 ? "" : "s"} · ${order.items.length} line${order.items.length === 1 ? "" : "s"}</p>
            </div>
            <div class="order-total">$${formatPrice(order.total)}</div>
            <a class="btn btn-outline btn-sm" href="order.html?order=${encodeURIComponent(order.id)}">View order</a>
          </div>`;
            }).join("")}
          </div>
        `;
      }
    })
    .catch(() => {
      root.innerHTML = `
        <div class="empty-state">
          <h3>Could not load orders</h3>
          <p style="color:var(--color-text-muted);">Network error. Please try again.</p>
          <a class="btn btn-primary" href="categories.html">Browse categories</a>
        </div>
      `;
    });
}
