/* ============================================================
   Active Life Medical — Shared layout injection
   Injects the site header and footer into placeholder elements
   (#site-header / #site-footer) on every page, so the markup is
   defined once instead of being duplicated across HTML files.
   Uses inline templates rather than fetch(), so it works when
   the site is opened directly from disk (file://), not just
   when served over http(s).
   ============================================================ */

function renderSiteHeader() {
  const page = location.pathname.split("/").pop() || "index.html";
  const isHome = page === "index.html";
  const isProducts = page === "products.html" || page === "product.html";
  const isCategories = page === "categories.html" || page === "category.html";
  const isAbout = page === "about.html";

  const header = `
  <header class="site-header">
    <div class="container">
      <a href="index.html" class="brand">
        <img class="brand-mark" src="assets/logo.png" alt="" width="34" height="34">
        <span>Active Life Medical<span class="eyebrow">Clinical Supply Co.</span></span>
      </a>
      <nav class="main-nav" id="main-nav">
        <a href="index.html" class="${isHome ? "active" : ""}">Home</a>
        <a href="products.html" class="${isProducts ? "active" : ""}">Products</a>
        <a href="categories.html" class="${isCategories ? "active" : ""}">Categories</a>
        <a href="about.html" class="${isAbout ? "active" : ""}">About</a>
        <div class="mobile-auth" id="auth-slot-mobile"></div>
      </nav>
      <div class="header-actions">
        <a href="cart.html" class="icon-btn" aria-label="View cart">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>
          <span class="cart-count" id="cart-count">0</span>
        </a>
        <a href="orders.html" class="icon-btn" aria-label="View order history">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4h8V2"/><rect x="5" y="2" width="14" height="20" rx="2"/><path d="M9 10h6"/><path d="M9 14h6"/><path d="M9 18h3"/></svg>
        </a>
        <div id="auth-slot"></div>
        <button type="button" class="icon-btn nav-toggle" id="nav-toggle" aria-label="Open menu" aria-expanded="false" aria-controls="main-nav">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18"/><path d="M3 12h18"/><path d="M3 18h18"/></svg>
        </button>
      </div>
    </div>
  </header>`;

  const slot = document.getElementById("site-header");
  if (slot) slot.outerHTML = header;
}

function renderSiteFooter() {
  const slot = document.getElementById("site-footer");
  if (!slot) return;
  const isFull = slot.dataset.footer === "full";

  const footerGrid = isFull ? `
      <div class="footer-grid">
        <div class="footer-brand">
          <div class="brand" style="color:#fff; margin-bottom:10px;">
            <img class="brand-mark footer-mark" src="assets/logo.png" alt="" width="34" height="34">
            <span>Active Life Medical</span>
          </div>
          <p>Clinical-grade medical devices and home care equipment, with full specs and honest stock levels.</p>
        </div>
        <div>
          <h4>Shop</h4>
          <a href="products.html">Products</a>
          <a href="categories.html">Categories</a>
          <a href="cart.html">Cart</a>
        </div>
        <div>
          <h4>Account</h4>
          <a href="login.html">Log in</a>
          <a href="register.html">Create account</a>
          <a href="orders.html">Order history</a>
        </div>
        <div>
          <h4>Company</h4>
          <a href="about.html">About</a>
        </div>
      </div>
` : "";

  // Compact footers (product/cart/checkout/login/register) get a small centered
  // brand row so the logo appears site-wide; the full footer has its own block.
  const footerBrand = isFull ? "" : `
      <div class="brand" style="color:#fff; justify-content:center; margin-bottom:18px;">
        <img class="brand-mark footer-mark" src="assets/logo.png" alt="" width="34" height="34">
        <span>Active Life Medical</span>
      </div>
`;

  // Compact footers (product/cart/checkout/login/register) originally had no
  // border or top padding on the footer-bottom row — preserve that look.
  const bottomStyle = isFull ? "" : ' style="border:none; padding-top:0;"';

  slot.outerHTML = `
  <footer class="site-footer">
    <div class="container">
      ${footerGrid}
      ${footerBrand}
      <div class="footer-bottom"${bottomStyle}>
        <span>© <span id="year"></span> Active Life Medical Clinical Supply Co. Demo storefront — not for real medical purchases.</span>
        <span>HTML5 · CSS3 · JavaScript</span>
      </div>
    </div>
  </footer>`;
}

// Run synchronously at the end of <body>: the placeholder elements above
// already exist, so the header/footer are in place before first paint and
// before main.js's DOMContentLoaded wiring (auth slot, cart badge, year).
renderSiteHeader();
renderSiteFooter();

// Mobile menu: the toggle is only visible below the desktop breakpoint (CSS),
// and the nav becomes a dropdown panel below it, so wiring it here is safe.
const navToggle = document.getElementById("nav-toggle");
const mainNav = document.getElementById("main-nav");
if (navToggle && mainNav) {
  navToggle.addEventListener("click", () => {
    const open = mainNav.classList.toggle("open");
    navToggle.setAttribute("aria-expanded", String(open));
    navToggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  });
  // A nav link navigates away anyway, but close the panel for same-page clicks.
  mainNav.addEventListener("click", (e) => {
    if (e.target.closest("a")) {
      mainNav.classList.remove("open");
      navToggle.setAttribute("aria-expanded", "false");
      navToggle.setAttribute("aria-label", "Open menu");
    }
  });
}
