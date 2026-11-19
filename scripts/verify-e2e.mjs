/* Throwaway E2E check: load the storefront in headless Chrome and confirm
   the catalog (categories + featured products) actually renders. */
import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";
function findChromeReal() {
  const pf = process.env["ProgramFiles"] || "C:\\Program Files";
  const pf86 = process.env["ProgramFiles(x86)"] || "C:\\Program Files (x86)";
  const candidates = [
    path.join(pf, "Google/Chrome/Application/chrome.exe"),
    path.join(pf86, "Google/Chrome/Application/chrome.exe"),
    path.join(process.env.LOCALAPPDATA || "", "Google/Chrome/Application/chrome.exe"),
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
  ];
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return null;
}

const BASE = process.env.BASE_URL || "http://localhost:8000";
const chromePath = findChromeReal();
if (!chromePath) { console.error("Chrome not found"); process.exit(1); }

const browser = await puppeteer.launch({ executablePath: chromePath, headless: "new" });
try {
  const page = await browser.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on("console", m => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("requestfailed", r => failedRequests.push(`${r.url()} → ${r.failure()?.errorText}`));
  page.on("response", r => { if (r.status() >= 400) failedRequests.push(`${r.url()} → HTTP ${r.status()}`); });

  await page.goto(BASE, { waitUntil: "networkidle2", timeout: 30000 });
  // give catalog JS a moment to render
  await new Promise(r => setTimeout(r, 2500));

  const result = await page.evaluate(() => ({
    title: document.title,
    categoryCards: document.querySelectorAll("#category-grid > *").length,
    featuredCards: document.querySelectorAll("#featured-strip > *").length,
    loadingSpinners: document.querySelectorAll(".catalog-loading").length,
    errorBoxes: document.querySelectorAll(".catalog-error").length,
    firstCategory: document.querySelector("#category-grid h3")?.textContent || null,
    firstFeatured: document.querySelector("#featured-strip .product-name, #featured-strip h3")?.textContent || null,
  }));

  console.log(JSON.stringify(result, null, 2));
  console.log("--- console errors:", consoleErrors.length ? consoleErrors : "none");
  console.log("--- failed requests:", failedRequests.length ? failedRequests : "none");

  const ok = result.categoryCards >= 3 && result.featuredCards > 0 &&
             result.errorBoxes === 0 && failedRequests.length === 0;
  console.log(ok ? "\n✅ E2E PASS — catalog renders with data" : "\n❌ E2E FAIL");
  process.exitCode = ok ? 0 : 1;
} finally {
  await browser.close();
}
