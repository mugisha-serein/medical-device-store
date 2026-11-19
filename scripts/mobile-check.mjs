/* ============================================================
   Active Life Medical — narrow-viewport layout check
   Usage: node scripts/mobile-check.mjs
   Serves the site, then for each page at 320/375/390/768px
   (logged-out and logged-in) reports any element that sticks
   out of the viewport or causes page-level horizontal scroll.
   Requires Chrome (CHROME_PATH or standard paths).
   ============================================================ */

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

/* The audit callback below runs inside the browser page context. */
/* global document, getComputedStyle */

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".json": "application/json",
};

const server = http.createServer((req, res) => {
  let urlPath;
  try {
    urlPath = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
  } catch {
    res.writeHead(400);
    res.end();
    return;
  }
  let filePath = path.normalize(path.join(ROOT, urlPath));
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403);
    res.end();
    return;
  }
  if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
    filePath = path.join(filePath, "index.html");
  }
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end("Not found");
      return;
    }
    res.writeHead(200, { "Content-Type": MIME[path.extname(filePath)] || "application/octet-stream" });
    res.end(data);
  });
});

function findChrome() {
  if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) {
    return process.env.CHROME_PATH;
  }
  const candidates = [];
  if (process.platform === "win32") {
    const pf = process.env.ProgramFiles || "C:/Program Files";
    const pf86 = process.env["ProgramFiles(x86)"] || "C:/Program Files (x86)";
    candidates.push(
      path.join(pf, "Google/Chrome/Application/chrome.exe"),
      path.join(pf86, "Google/Chrome/Application/chrome.exe"),
      path.join(process.env.LOCALAPPDATA || "", "Google/Chrome/Application/chrome.exe")
    );
  } else if (process.platform === "darwin") {
    candidates.push("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  } else {
    candidates.push("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser");
  }
  return candidates.find((c) => c && fs.existsSync(c)) || null;
}

const chromePath = findChrome();
if (!chromePath) {
  console.error("Chrome/Chromium not found — install it or set CHROME_PATH");
  process.exit(1);
}

await new Promise((resolve) => server.listen(0, resolve));
const baseUrl = `http://127.0.0.1:${server.address().port}`;

const browser = await puppeteer.launch({
  executablePath: chromePath,
  headless: true,
  args: [
    "--no-first-run",
    "--no-default-browser-check",
    "--host-resolver-rules=MAP fonts.googleapis.com 127.0.0.1, MAP fonts.gstatic.com 127.0.0.1",
    ...(process.platform !== "win32" ? ["--no-sandbox"] : []),
  ],
  timeout: 20000,
});

const page = await browser.newPage();
const errors = [];
page.on("pageerror", (err) => errors.push(String(err)));
page.on("console", (msg) => {
  // The font-host mapping produces expected ERR_CONNECTION_REFUSED noise;
  // anything else is a real regression worth reporting.
  if (msg.type() === "error" && !msg.text().includes("ERR_CONNECTION_REFUSED")) errors.push(msg.text());
});

const settle = () => new Promise((resolve) => setTimeout(resolve, 350));

const PAGES = [
  ["home", "index.html"],
  ["products", "products.html"],
  ["categories", "categories.html"],
  ["about", "about.html"],
  ["category", "category.html?id=diagnostic"],
  ["product", "product.html?id=dg-001"],
  ["cart", "cart.html"],
  ["checkout", "checkout.html"],
  ["confirmation", "confirmation.html?order=ORD-0001"],
  ["orders", "orders.html"],
  ["order", "order.html?id=ORD-0001"],
  ["login", "login.html"],
  ["register", "register.html"],
];

// Reports page-level scroll and any visible element overflowing the viewport.
async function audit(width) {
  const result = await page.evaluate((w) => {
    const issues = [];
    const vw = w;
    const doc = document.documentElement;
    const scrollW = Math.max(doc.scrollWidth, document.body.scrollWidth);
    if (scrollW > vw + 1) {
      issues.push(`PAGE horizontal scroll: ${scrollW}px > viewport ${vw}px`);
    }
    const seen = new Set();
    for (const el of document.querySelectorAll("body *")) {
      if (seen.has(el)) continue;
      seen.add(el);
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) === 0) continue;
      // Skip elements clipped by a scroll container (e.g. the horizontally
      // scrollable featured strip) — they scroll inside it, not the page.
      let clipped = false;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const pc = getComputedStyle(p);
        if (pc.overflowX === "auto" || pc.overflowX === "scroll" || pc.overflowX === "hidden") {
          clipped = true;
          break;
        }
      }
      if (clipped) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      const overflowRight = Math.round(r.right) - vw;
      const overflowLeft = Math.round(r.left);
      if (overflowRight > 1 || overflowLeft < -1) {
        const id = el.id ? `#${el.id}` : "";
        const cls = typeof el.className === "string" && el.className ? `.${el.className.trim().split(/\s+/).join(".")}` : "";
        const tag = el.tagName.toLowerCase();
        issues.push(`${tag}${id}${cls}: left=${Math.round(r.left)} right=${Math.round(r.right)} (viewport ${vw}px, ${tag === "img" || tag === "svg" ? "media" : "text=" + (el.textContent || "").trim().slice(0, 40)})`);
      }
    }
    return issues;
  }, width);
  return result;
}

let failures = 0;

async function checkState(stateName, setupFn) {
  for (const [name, url] of PAGES) {
    for (const width of [320, 375, 390, 768]) {
      await page.setViewport({ width, height: 800 });
      await page.goto(`${baseUrl}/${url}`, { waitUntil: "domcontentloaded", timeout: 15000 });
      await settle();
      if (setupFn) await setupFn();
      const issues = await audit(width);
      if (issues.length) {
        failures += 1;
        console.log(`\n✗ ${stateName} · ${name} @ ${width}px`);
        issues.forEach((i) => console.log(`    ${i}`));
      }
    }
  }
}

console.log("=== Logged-out state ===");
await checkState("logged-out", null);

// Register an account and add an item, then audit the account-gated states.
await page.setViewport({ width: 1440, height: 900 });
await page.goto(`${baseUrl}/register.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
await page.type("#name", "Mobile Check");
await page.type("#email", `mobile${Date.now()}@example.com`);
await page.type("#password", "password123");
await page.type("#confirm", "password123");
await page.click("#register-form button[type=submit]");
await page.waitForFunction("location.pathname.endsWith('/index.html')", { timeout: 8000 });
await page.goto(`${baseUrl}/product.html?id=dg-001`, { waitUntil: "domcontentloaded", timeout: 15000 });
await page.click("#add-to-cart-btn");
await new Promise((resolve) => setTimeout(resolve, 600));

console.log("\n=== Logged-in state (1 item in cart) ===");
await checkState("logged-in", null);

await browser.close();
await new Promise((resolve) => server.close(resolve));

console.log(errors.length ? `\n${errors.length} console/page errors:\n${errors.join("\n")}` : "\nNo console/page errors");
console.log(failures === 0 ? "\nAll pages clean at every width." : `\n${failures} page-width combination(s) with overflow.`);
process.exit(failures === 0 ? 0 : 1);
