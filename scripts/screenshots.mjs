/* ============================================================
   Active Life Medical — screenshot capture for visual review
   Usage: node scripts/screenshots.mjs
   Serves the site on a random port, registers a throwaway
   account, adds one item to the cart, and saves full-page PNGs
   of home / category / product / cart / checkout / login into
   screenshots/. Requires Chrome (CHROME_PATH or standard paths).
   ============================================================ */

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(ROOT, "screenshots");

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
fs.mkdirSync(OUT, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: chromePath,
  headless: true,
  args: [
    "--no-first-run",
    "--no-default-browser-check",
    // Fail fast on external font hosts so page loads can't hang.
    "--host-resolver-rules=MAP fonts.googleapis.com 127.0.0.1, MAP fonts.gstatic.com 127.0.0.1",
    ...(process.platform !== "win32" ? ["--no-sandbox"] : []),
  ],
  timeout: 20000,
});

const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });
page.on("pageerror", (err) => console.error("PAGE ERROR:", String(err)));

const settle = () => new Promise((resolve) => setTimeout(resolve, 500));

async function shot(url, name) {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 15000 });
  await settle();
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  console.log(`saved screenshots/${name}.png`);
}

// 1. Login page — must be captured logged-out (login.html bounces logged-in users).
await shot(`${baseUrl}/login.html`, "login");

// 2. Register a throwaway account (lands on the home page after ~500ms).
await page.goto(`${baseUrl}/register.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
await page.type("#name", "Palette Check");
await page.type("#email", `palette${Date.now()}@example.com`);
await page.type("#password", "password123");
await page.type("#confirm", "password123");
await page.click("#register-form button[type=submit]");
await page.waitForFunction("location.pathname.endsWith('/index.html')", { timeout: 8000 });

// 3. Public/product pages (product captured before adding, so no toast overlay).
await shot(`${baseUrl}/index.html`, "home");
await shot(`${baseUrl}/category.html?id=diagnostic`, "category");
await shot(`${baseUrl}/product.html?id=dg-001`, "product");

// 4. Add an item, then capture the account-gated pages.
await page.goto(`${baseUrl}/product.html?id=dg-001`, { waitUntil: "domcontentloaded", timeout: 15000 });
await page.click("#add-to-cart-btn");
await new Promise((resolve) => setTimeout(resolve, 600));
await shot(`${baseUrl}/cart.html`, "cart");
await shot(`${baseUrl}/checkout.html`, "checkout");

// 5. Narrow-viewport captures (390px) for mobile review.
await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });
for (const [name, url] of [
  ["mobile-home", `${baseUrl}/index.html`],
  ["mobile-category", `${baseUrl}/category.html?id=diagnostic`],
  ["mobile-product", `${baseUrl}/product.html?id=dg-001`],
  ["mobile-cart", `${baseUrl}/cart.html`],
  ["mobile-checkout", `${baseUrl}/checkout.html`],
]) {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 15000 });
  await settle();
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
  console.log(`saved screenshots/${name}.png`);
}

// 6. Log out (login.html bounces logged-in users), then capture login at mobile width.
await page.goto(`${baseUrl}/index.html`, { waitUntil: "domcontentloaded", timeout: 15000 });
await page.click("#logout-btn");
await new Promise((resolve) => setTimeout(resolve, 900));
await shot(`${baseUrl}/login.html`, "mobile-login");

await browser.close();
await new Promise((resolve) => server.close(resolve));
console.log(`\nDone — ${fs.readdirSync(OUT).filter((f) => f.endsWith(".png")).length} screenshots in screenshots/`);
