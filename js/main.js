/* ============================================================
   Active Life Medical — Shared UI wiring
   Runs on every page: header auth state, cart badge, toasts.
   ============================================================ */

/* exported escapeHtml, renderHeaderAuth, renderCartBadge, showToast, currentNextQuery */
/* global getSession, isLoggedIn, logoutUser, getCartCount, waitForCatalog, catalogLoadFailed, catalogErrorMessage */

/** Escapes a string for safe interpolation into HTML (text or attributes). */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function initials(name) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map(p => p[0].toUpperCase())
    .join("");
}

// Preserves a ?next= target from the current URL onto another page's link, so
// redirect chains (e.g. login → register) don't lose the intended destination.
function currentNextQuery() {
  const next = new URLSearchParams(location.search).get("next");
  return next ? `?next=${encodeURIComponent(next)}` : "";
}

function renderHeaderAuth() {
  // Two slots: the header actions (desktop) and the mobile menu panel. Only one
  // is visible at a time (CSS), but both get the same content.
  const slots = document.querySelectorAll("#auth-slot, #auth-slot-mobile");
  if (!slots.length) return;
  const session = getSession();

  slots.forEach(slot => {
    if (session) {
      slot.innerHTML = `
        <div class="user-chip">
          <div class="avatar">${escapeHtml(initials(session.name))}</div>
          <span>${escapeHtml(session.name.split(" ")[0])}</span>
        </div>
        <button class="btn btn-ghost btn-sm logout-btn" type="button">Log out</button>
      `;
    } else {
      const nextQuery = currentNextQuery();
      slot.innerHTML = `
        <a class="btn btn-outline btn-sm" href="login.html${nextQuery}">Log in</a>
        <a class="btn btn-primary btn-sm" href="register.html${nextQuery}">Sign up</a>
      `;
    }
  });

  document.querySelectorAll(".logout-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      logoutUser();
      showToast("You've been logged out.", "info");
      setTimeout(() => (location.href = "index.html"), 500);
    });
  });
}

function renderCartBadge() {
  const el = document.getElementById("cart-count");
  if (!el) return;
  const count = isLoggedIn() ? getCartCount() : 0;
  el.textContent = count;
  el.style.display = count > 0 ? "flex" : "none";
}

function showToast(message, type = "info", duration) {
  let toast = document.getElementById("global-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "global-toast";
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.className = `toast show ${type}`;
  clearTimeout(window.__toastTimer);
  const ms = duration || (type === "error" ? 5000 : 2800);
  window.__toastTimer = setTimeout(() => toast.classList.remove("show"), ms);
}

document.addEventListener("DOMContentLoaded", () => {
  renderHeaderAuth();
  renderCartBadge();
  const yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  // Global catalog failure toast — fires once if the API is unreachable,
  // so the user sees feedback even before page-level error states render.
  waitForCatalog().then(() => {
    if (catalogLoadFailed()) {
      showToast(
        "Unable to load the catalog. Some content may be unavailable. ",
        "error"
      );
    }
  });
});
