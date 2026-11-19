/* ============================================================
   Active Life Medical — zero-dependency static dev server
   Usage: node scripts/serve.mjs   (or: npm run dev)
   Serves the project folder on http://localhost:8000
   (override with the PORT env var).
   Proxies /api/* requests to the FastAPI backend
   (override with the BACKEND_URL env var, default http://localhost:8001).
   ============================================================ */

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PORT = Number(process.env.PORT) || 8000;
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8001";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

const server = http.createServer((req, res) => {
  let urlPath;
  try {
    urlPath = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
  } catch {
    res.writeHead(400);
    res.end("Bad request");
    return;
  }

  /* ---- proxy /api/* and /docs /openapi.json to FastAPI backend ---- */
  if (urlPath.startsWith("/api/") || urlPath.startsWith("/docs") || urlPath === "/openapi.json") {
    const backendTarget = new URL(req.url, BACKEND_URL);
    const proxyReq = http.request(
      backendTarget,
      {
        method: req.method,
        headers: { ...req.headers, host: new URL(BACKEND_URL).host },
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
        proxyRes.pipe(res);
      }
    );

    proxyReq.on("error", () => {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: "Backend unavailable. Is FastAPI running?" }));
    });

    req.pipe(proxyReq);
    return;
  }

  /* ---- serve static frontend files ---- */
  let filePath = path.normalize(path.join(ROOT, urlPath));
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403);
    res.end("Forbidden");
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

server.listen(PORT, () => {
  console.log(`Active Life Medical frontend → http://localhost:${PORT}`);
  console.log(`Proxying /api/* → ${BACKEND_URL}`);
  console.log(`Start FastAPI with: cd backend && uvicorn app.main:app --port 8001 --reload`);
});
