/* ============================================================
   Active Life Medical — Cart Management
   Cart is scoped per logged-in user: md_cart_<userId>
   Cart stays client-side pre-checkout; stock is validated
   server-side at checkout time against the live API.
   ============================================================ */

/* exported addToCart, updateCartQty, removeFromCart, clearCart, getCartCount, getCartDetailed, checkStockFromAPI */
/* global getSession, isLoggedIn, getProductById, authFetch, API_BASE */

function cartKeyFor(userId) {
  return `md_cart_${userId}`;
}

function getCart() {
  const session = getSession();
  if (!session) return [];
  try {
    return JSON.parse(localStorage.getItem(cartKeyFor(session.userId))) || [];
  } catch (e) {
    return [];
  }
}

function saveCart(cart) {
  const session = getSession();
  if (!session) return;
  localStorage.setItem(cartKeyFor(session.userId), JSON.stringify(cart));
}

/**
 * Attempts to add a product to the cart.
 * Returns { ok: true } on success, or { ok: false, authRequired: true }
 * if the user is not logged in — caller should redirect to login.
 */
function addToCart(productId, qty = 1) {
  if (!isLoggedIn()) {
    return { ok: false, authRequired: true };
  }
  const product = getProductById(productId);
  if (!product) return { ok: false, error: "Product not found." };
  if (product.stock <= 0) return { ok: false, error: "This item is out of stock." };

  const cart = getCart();
  const existing = cart.find(line => line.productId === productId);
  const currentQty = existing ? existing.qty : 0;
  // Only as much as is still available beyond what's already in the cart.
  const available = Math.max(0, product.stock - currentQty);
  const added = Math.min(qty, available);
  const nextQty = currentQty + added;

  if (existing) {
    existing.qty = nextQty;
  } else {
    cart.push({ productId, qty: nextQty });
  }
  saveCart(cart);

  const result = { ok: true, qty: nextQty };
  if (added < qty) {
    result.clamped = true;
    result.message = added > 0
      ? `Only ${available} more available — added ${added} to your cart.`
      : "No more available — this item is already at the stock limit in your cart.";
  }
  return result;
}

function updateCartQty(productId, qty) {
  const cart = getCart();
  const line = cart.find(l => l.productId === productId);
  if (!line) return;
  const product = getProductById(productId);
  const max = product ? product.stock : 99;
  line.qty = Math.max(1, Math.min(qty, max));
  saveCart(cart);
  return line.qty;
}

function removeFromCart(productId) {
  const cart = getCart().filter(l => l.productId !== productId);
  saveCart(cart);
}

function clearCart() {
  saveCart([]);
}

function getCartCount() {
  return getCart().reduce((sum, l) => sum + l.qty, 0);
}

/** Joins raw cart lines with live product data and computes totals. */
function getCartDetailed() {
  const lines = getCart()
    .map(l => {
      const product = getProductById(l.productId);
      if (!product) return null;
      return {
        productId: l.productId,
        qty: l.qty,
        product,
        lineTotal: product.price * l.qty
      };
    })
    .filter(Boolean);

  const subtotal = lines.reduce((sum, l) => sum + l.lineTotal, 0);
  const shipping = lines.length === 0 ? 0 : (subtotal > 250 ? 0 : 12.5);
  const total = subtotal + shipping;

  return { lines, subtotal, shipping, total };
}

/**
 * Validates stock against the live API for all items in the cart.
 * Returns { ok: true } or { ok: false, unavailable: [...] } with items
 * that have insufficient stock.
 */
async function checkStockFromAPI() {
  const cart = getCart();
  if (cart.length === 0) return { ok: true, unavailable: [] };

  const unavailable = [];

  for (const line of cart) {
    try {
      const response = await authFetch(`${API_BASE}/inventory/products/${line.productId}`);
      if (response.ok) {
        const data = await response.json();
        if (data.quantity_available < line.qty) {
          unavailable.push({
            productId: line.productId,
            requested: line.qty,
            available: data.quantity_available,
          });
        }
      }
    } catch (e) {
      // If we can't reach the API, proceed with client-side check
      // (the server will reject the order anyway if stock is insufficient)
    }
  }

  if (unavailable.length > 0) {
    return { ok: false, unavailable };
  }
  return { ok: true, unavailable: [] };
}
