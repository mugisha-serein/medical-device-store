/* ============================================================
   Active Life Medical — Order History
   Orders are fetched from the backend API. This module provides
   async functions for order operations.
   ============================================================ */

/* exported getOrders, fetchOrderById, fetchOrderHistory */
/* global authFetch, isLoggedIn, API_BASE */

/**
 * Fetches the current user's order history from the API.
 * Returns { ok: true, orders } or { ok: false, error }.
 */
async function fetchOrderHistory({ skip = 0, limit = 20 } = {}) {
  if (!isLoggedIn()) {
    return { ok: false, error: "Please log in to view orders.", orders: [] };
  }

  try {
    const response = await authFetch(
      `${API_BASE}/orders?skip=${skip}&limit=${limit}`
    );

    if (!response.ok) {
      const data = await response.json();
      return { ok: false, error: data.detail || "Failed to fetch orders.", orders: [] };
    }

    const orders = await response.json();
    return { ok: true, orders };
  } catch (e) {
    return { ok: false, error: "Network error. Please try again.", orders: [] };
  }
}

/**
 * Fetches a single order by ID from the API.
 * Returns { ok: true, order } or { ok: false, error }.
 */
async function fetchOrderById(orderId) {
  if (!isLoggedIn()) {
    return { ok: false, error: "Please log in to view orders." };
  }

  try {
    const response = await authFetch(
      `${API_BASE}/orders/${encodeURIComponent(orderId)}`
    );

    if (!response.ok) {
      return { ok: false, error: "Order not found." };
    }

    const order = await response.json();
    return { ok: true, order };
  } catch (e) {
    return { ok: false, error: "Network error. Please try again." };
  }
}
