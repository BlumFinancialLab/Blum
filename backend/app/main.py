from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.bootstrap import bootstrap_database


settings = get_settings()

app = FastAPI(
    title="Blum AI Financial Intelligence API",
    version=settings.app_version,
    description=(
        "Open-source AI financial intelligence backend for equities, ETFs, "
        "semantic news analysis, signal scoring, explainability and validation."
    ),
)

origins = ["*"] if settings.cors_origins == "*" else [item.strip() for item in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

STATIC_DIR = Path(__file__).parent / "static"
if (STATIC_DIR / "_next").exists():
    app.mount("/_next", StaticFiles(directory=STATIC_DIR / "_next"), name="next-static")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def startup() -> None:
    with SessionLocal() as db:
        bootstrap_database(db)


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    if not STATIC_DIR.exists():
        return {"message": "Frontend build not found. Run the Next.js build or use the API docs at /docs."}
    target = STATIC_DIR / full_path
    if target.is_file():
        return FileResponse(target)
    html_file = target / "index.html"
    if html_file.is_file():
        return FileResponse(html_file)
    return FileResponse(STATIC_DIR / "index.html")
