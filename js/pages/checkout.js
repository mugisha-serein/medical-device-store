/* ============================================================
   Active Life Medical — Checkout page: shipping/payment form, auth guards
   at render and submit time, per-field validation, and a fresh
   stock re-check against the live API when the order is placed.
   ============================================================ */

/* global isLoggedIn, redirectToLogin, getCartDetailed, getSession, getProductById, escapeHtml, formatPrice, clearCart, validateFields, attachLiveValidation, authFetch, checkStockFromAPI, API_BASE, waitForCatalog, catalogLoadFailed, catalogErrorMessage, CATALOG_LOADING_HTML, catalogErrorHTML */

const root = document.getElementById("checkout-root");

const CHECKOUT_FIELDS = [
  "full-name", "address", "city", "postal", "phone",
  "card-name", "card-number", "card-exp", "card-cvc"
];

function fieldValue(id) {
  return (document.getElementById(id).value || "").trim();
}

/* ---- card input auto-formatting ---- */

/** Sets a formatted value while keeping the caret aligned with the digits the
 *  user is editing (so mid-string edits don't jump to the end). */
function setFormatted(input, formatted) {
  if (input.value === formatted) return;
  const start = input.selectionStart != null ? input.selectionStart : input.value.length;
  const digitsBefore = input.value.slice(0, start).replace(/\D/g, "").length;
  input.value = formatted;
  let caret = formatted.length;
  let seen = 0;
  for (let i = 0; i < formatted.length; i++) {
    if (/\d/.test(formatted[i])) seen++;
    if (seen === digitsBefore) {
      let j = i + 1;
      while (j < formatted.length && !/\d/.test(formatted[j])) j++;
      caret = j;
      break;
    }
  }
  input.setSelectionRange(caret, caret);
}

/** Groups up to 16 digits into 4-digit blocks: 4242 4242 4242 4242. */
function formatCardNumber(input) {
  const digits = input.value.replace(/\D/g, "").slice(0, 16);
  const formatted = digits.replace(/(\d{4})(?=\d)/g, "$1 ").trim();
  setFormatted(input, formatted);
}

/* ---- card brand detection & logos ---- */

const CARD_BRAND_ICONS = {
  visa: `<svg viewBox="0 0 60 20" aria-hidden="true"><rect width="60" height="20" rx="4" fill="#1A1F71"/><text x="30" y="14" font-family="Arial, Helvetica, sans-serif" font-size="11" font-weight="700" font-style="italic" fill="#fff" text-anchor="middle" letter-spacing="0.5">VISA</text></svg>`,
  mastercard: `<svg viewBox="0 0 36 22" aria-hidden="true"><circle cx="13" cy="11" r="10" fill="#EB001B"/><circle cx="23" cy="11" r="10" fill="#F79E1B"/><path d="M18 2.34 A10 10 0 0 1 18 19.66 A10 10 0 0 1 18 2.34 Z" fill="#FF5F00"/></svg>`,
  amex: `<svg viewBox="0 0 60 20" aria-hidden="true"><rect width="60" height="20" rx="4" fill="#2E77BC"/><text x="30" y="14" font-family="Arial, Helvetica, sans-serif" font-size="10" font-weight="700" fill="#fff" text-anchor="middle" letter-spacing="1">AMEX</text></svg>`
};

function detectCardBrand(digits) {
  if (digits.length < 2) return null;
  if (/^3[47]/.test(digits)) return "amex";
  if (/^4/.test(digits)) return "visa";
  if (/^(5[1-5]|2[2-7])/.test(digits)) return "mastercard";
  return null;
}

function updateCardBrand(input) {
  const badge = document.getElementById("card-brand");
  if (!badge) return;
  const brand = detectCardBrand(input.value.replace(/\D/g, ""));
  if (brand) {
    badge.innerHTML = CARD_BRAND_ICONS[brand];
    badge.setAttribute("aria-label", brand === "amex" ? "American Express" : brand.charAt(0).toUpperCase() + brand.slice(1));
  } else {
    badge.innerHTML = "";
    badge.removeAttribute("aria-label");
  }
}

function formatCardExpiry(input) {
  const digits = input.value.replace(/\D/g, "").slice(0, 4);
  const formatted = digits.length > 2 ? `${digits.slice(0, 2)}/${digits.slice(2)}` : digits;
  setFormatted(input, formatted);
}

/* ---- per-field validation rules ---- */

const CHECKOUT_RULES = {
  "full-name": value => (value ? "" : "Enter the recipient's full name."),
  address: value => (value ? "" : "Enter a street address."),
  city: value => (value ? "" : "Enter a city."),
  postal: value => (value ? "" : "Enter a postal code."),
  phone: value => (value.replace(/\D/g, "").length >= 7 ? "" : "Enter a valid phone number."),
  "card-name": value => (value ? "" : "Enter the name on the card."),
  "card-number": value => {
    const digits = value.replace(/\D/g, "");
    return (digits.length >= 13 && digits.length <= 19) ? "" : "Enter a valid card number (13–19 digits).";
  },
  "card-exp": value => {
    const m = /^(0[1-9]|1[0-2])\/(\d{2})$/.exec(value);
    if (!m) return "Enter the expiry as MM/YY.";
    const now = new Date();
    const expYear = 2000 + parseInt(m[2], 10);
    const expMonth = parseInt(m[1], 10);
    if (expYear < now.getFullYear() || (expYear === now.getFullYear() && expMonth < now.getMonth() + 1)) {
      return "This card has expired.";
    }
    return "";
  },
  "card-cvc": value => (/^\d{3,4}$/.test(value) ? "" : "Enter a valid CVC (3–4 digits).")
};

/* ---- page render (also re-invoked when the cart/stock changed at submit) ---- */

function renderCheckout(notice) {
  const { lines, subtotal, shipping, total } = getCartDetailed();

  if (lines.length === 0) {
    root.innerHTML = `
      <div class="empty-state">
        <svg class="vitals-line" viewBox="0 0 200 60" xmlns="http://www.w3.org/2000/svg">
          <polyline points="0,30 30,30 40,10 50,50 60,20 70,30 130,30 140,15 150,45 160,30 200,30" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <h3>Your cart is empty</h3>
        <p>Add a few items before heading to checkout.</p>
        <a class="btn btn-primary" href="categories.html">Browse categories</a>
      </div>
    `;
    return;
  }

  const session = getSession();

  root.innerHTML = `
    <div class="checkout-layout">
      <div>
        <form id="checkout-form" novalidate>
          <div class="checkout-section">
            <h3><span class="step-num">1</span> Shipping details</h3>
            <div class="field" id="field-full-name">
              <label for="full-name">Full name</label>
              <input type="text" id="full-name" value="${escapeHtml(session.name)}" required>
              <div class="field-error">Enter the recipient's full name.</div>
            </div>
            <div class="field" id="field-address">
              <label for="address">Street address</label>
              <input type="text" id="address" placeholder="123 Clinic Road" required>
              <div class="field-error">Enter a street address.</div>
            </div>
            <div class="form-row">
              <div class="field" id="field-city">
                <label for="city">City</label>
                <input type="text" id="city" placeholder="Kigali" required>
                <div class="field-error">Enter a city.</div>
              </div>
              <div class="field" id="field-postal">
                <label for="postal">Postal code</label>
                <input type="text" id="postal" placeholder="00000" required>
                <div class="field-error">Enter a postal code.</div>
              </div>
            </div>
            <div class="field" id="field-phone">
              <label for="phone">Phone number</label>
              <input type="tel" id="phone" placeholder="+250 7xx xxx xxx" required>
              <div class="field-error">Enter a valid phone number.</div>
            </div>
          </div>

          <div class="checkout-section">
            <h3><span class="step-num">2</span> Payment (mock)</h3>
            <div class="field" id="field-card-name">
              <label for="card-name">Name on card</label>
              <input type="text" id="card-name" value="${escapeHtml(session.name)}" required>
              <div class="field-error">Enter the name on the card.</div>
            </div>
            <div class="field" id="field-card-number">
              <label for="card-number">Card number</label>
              <div class="card-input-wrap">
                <input type="text" id="card-number" placeholder="4242 4242 4242 4242" maxlength="19" inputmode="numeric" autocomplete="cc-number" required>
                <span class="card-brand" id="card-brand" role="img"></span>
              </div>
              <div class="field-error">Enter a valid card number (13–19 digits).</div>
            </div>
            <div class="form-row">
              <div class="field" id="field-card-exp">
                <label for="card-exp">Expiry (MM/YY)</label>
                <input type="text" id="card-exp" placeholder="MM/YY" maxlength="5" inputmode="numeric" autocomplete="cc-exp" required>
                <div class="field-error">Enter the expiry as MM/YY.</div>
              </div>
              <div class="field" id="field-card-cvc">
                <label for="card-cvc">CVC</label>
                <input type="text" id="card-cvc" placeholder="123" maxlength="4" inputmode="numeric" autocomplete="cc-csc" required>
                <div class="field-error">Enter a valid CVC (3–4 digits).</div>
              </div>
            </div>
            <div class="form-msg" id="checkout-msg"></div>
            <button type="submit" class="btn btn-primary btn-block" id="place-order-btn">Place order — $${formatPrice(total)}</button>
            <p style="font-size:0.76rem; color:var(--color-text-muted); margin-top:10px; text-align:center;">This is a demo checkout. No real payment is processed.</p>
          </div>
        </form>
      </div>

      <div class="summary-card">
        <h3>Order review</h3>
        <div class="order-review-list">
          ${lines.map(l => `
            <div class="order-review-line">
              <span class="name">${l.product.name}</span>
              <span class="qty">×${l.qty} — $${formatPrice(l.lineTotal)}</span>
            </div>
          `).join("")}
        </div>
        <div class="summary-row"><span>Subtotal</span><span>$${formatPrice(subtotal)}</span></div>
        <div class="summary-row"><span>Shipping</span><span>${shipping === 0 ? "Free" : "$" + formatPrice(shipping)}</span></div>
        <div class="summary-row total"><span>Total</span><span>$${formatPrice(total)}</span></div>
      </div>
    </div>
  `;

  const form = document.getElementById("checkout-form");
  const msgBox = document.getElementById("checkout-msg");
  const placeBtn = document.getElementById("place-order-btn");

  if (notice) {
    msgBox.textContent = notice;
    msgBox.className = "form-msg show error";
  }

  // Format card inputs as user types
  const cardNumberInput = document.getElementById("card-number");
  cardNumberInput.addEventListener("input", () => {
    formatCardNumber(cardNumberInput);
    updateCardBrand(cardNumberInput);
  });
  const cardExpInput = document.getElementById("card-exp");
  cardExpInput.addEventListener("input", () => formatCardExpiry(cardExpInput));

  // Live per-field feedback
  attachLiveValidation(CHECKOUT_FIELDS, CHECKOUT_RULES);

  let placing = false;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    // Guard against double-submits
    if (placing) return;
    placing = true;
    placeBtn.disabled = true;
    placeBtn.textContent = "Placing order…";

    const resetButton = () => {
      placing = false;
      placeBtn.disabled = false;
      placeBtn.textContent = `Place order — $${formatPrice(total)}`;
    };

    // Guard 1: re-check auth at moment of submission
    if (!isLoggedIn()) {
      redirectToLogin("Your session expired. Please log in to complete checkout.");
      return;
    }

    // Guard 2: per-field validation
    const errors = validateFields(CHECKOUT_FIELDS, CHECKOUT_RULES);
    if (errors.length > 0) {
      msgBox.textContent = errors[0];
      msgBox.className = "form-msg show error";
      resetButton();
      return;
    }

    // Guard 3: re-read the cart at submit time
    const fresh = getCartDetailed();
    if (fresh.lines.length === 0) {
      msgBox.textContent = "Your cart is empty — add items before checking out.";
      msgBox.className = "form-msg show error";
      resetButton();
      return;
    }

    // Guard 4: validate stock against the live API
    const stockCheck = await checkStockFromAPI();
    if (!stockCheck.ok) {
      renderCheckout("Stock changed — review your cart before placing the order.");
      return;
    }

    // Guard 5: place order via API
    try {
      const orderPayload = {
        items: fresh.lines.map(l => ({
          product_id: l.productId,
          quantity: l.qty,
        })),
        shipping: {
          name: fieldValue("full-name"),
          address: fieldValue("address"),
          city: fieldValue("city"),
          postal: fieldValue("postal") || null,
          phone: fieldValue("phone"),
        },
      };

      const response = await authFetch(`${API_BASE}/orders`, {
        method: "POST",
        body: JSON.stringify(orderPayload),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to place order.");
      }

      const order = await response.json();

      // Clear cart and redirect to confirmation
      clearCart();
      location.href = `confirmation.html?order=${encodeURIComponent(order.id)}`;
    } catch (err) {
      msgBox.textContent = err.message || "Something went wrong. Please try again.";
      msgBox.className = "form-msg show error";
      resetButton();
    }
  });
}

// Guard 0: must be logged in to reach checkout, catalog must be loaded
if (!isLoggedIn()) {
  redirectToLogin("Please log in to check out.");
} else {
  root.innerHTML = CATALOG_LOADING_HTML;
  waitForCatalog().then(() => {
    if (catalogLoadFailed()) {
      root.innerHTML = catalogErrorHTML(catalogErrorMessage());
      return;
    }
    renderCheckout();
  });
}
