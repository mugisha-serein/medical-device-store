import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import engine

settings = get_settings()

# Frontend root: one level up from backend/ (the project root)
# In Docker, files are mounted at /frontend; in dev, walk up from backend/
_docker_mount = Path("/frontend")
FRONTEND_DIR = _docker_mount if _docker_mount.is_dir() else Path(__file__).resolve().parent.parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic — run: alembic upgrade head
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Active Life Medical — Medical Devices E-Commerce API",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and register routers
from app.identity.router import router as identity_router
from app.catalog.router import router as catalog_router
from app.inventory.router import router as inventory_router
from app.orders.router import router as orders_router
from app.payments.router import router as payments_router
from app.notifications.router import router as notifications_router

# Versioned API routes
app.include_router(identity_router, prefix="/api/v1")
app.include_router(catalog_router, prefix="/api/v1")
app.include_router(inventory_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


# ── Serve frontend static files ─────────────────────────────────────────────
# This is registered last so it doesn't shadow API routes.
# Only active when SERVE_FRONTEND=1 (set in docker-compose / production).
if os.environ.get("SERVE_FRONTEND") == "1":
    if FRONTEND_DIR.is_dir():
        # Mount static asset directories first (CSS, JS, assets)
        app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
        app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

        # Catch-all for HTML pages: serve index.html for known pages
        HTML_PAGES = [f.stem for f in FRONTEND_DIR.glob("*.html")]

        @app.get("/{page}.html", include_in_schema=False)
        async def serve_page(page: str):
            from fastapi.responses import FileResponse
            html_file = FRONTEND_DIR / f"{page}.html"
            if html_file.is_file():
                return FileResponse(str(html_file), media_type="text/html")
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Page not found")

        @app.get("/", include_in_schema=False)
        async def serve_index():
            from fastapi.responses import FileResponse
            return FileResponse(str(FRONTEND_DIR / "index.html"), media_type="text/html")
