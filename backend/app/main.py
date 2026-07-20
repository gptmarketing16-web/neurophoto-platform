from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api.admin import router as admin_router
from .api.auth_api import router as auth_router
from .api.max_webhook import router as max_router
from .api.projects import router as projects_router
from .api.users import router as users_router
from .auth import decode_session_token, ensure_owner
from .db import Base, SessionLocal, engine, get_db
from .models import User, Workspace
from .schema_compat import ensure_compatible_schema
from .services.canvas_cleanup import cleanup_expired_canvas_assets
from .services.jobs import cleanup_expired_jobs
from .settings import settings

STATIC_DIR = Path(__file__).parent / "static"


async def cleanup_loop() -> None:
    while True:
        await asyncio.to_thread(cleanup_expired_jobs)
        await asyncio.to_thread(cleanup_expired_canvas_assets)
        await asyncio.sleep(settings.cleanup_interval_seconds)


def validate_production_settings() -> None:
    if settings.app_env != "production":
        return
    problems: list[str] = []
    if settings.app_secret_key in {"local-development-key-change-me", "change-me"} or len(settings.app_secret_key) < 32:
        problems.append("APP_SECRET_KEY должен быть случайной строкой длиной минимум 32 символа")
    if settings.owner_password == "ChangeMe123!" or len(settings.owner_password) < 10:
        problems.append("OWNER_PASSWORD необходимо заменить")
    if settings.allow_mock_fallback:
        problems.append("ALLOW_MOCK_FALLBACK должен быть false")
    if not settings.secure_cookies:
        problems.append("SECURE_COOKIES должен быть true")
    if problems:
        raise RuntimeError("Production configuration error: " + "; ".join(problems))


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_settings()
    Base.metadata.create_all(bind=engine)
    ensure_compatible_schema()
    ensure_owner()
    cleanup_task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(
    title=settings.app_name,
    version="0.5.2",
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(admin_router)
app.include_router(users_router)
app.include_router(max_router)


PUBLIC_API_PATHS = {"/api/auth/login", "/api/max/webhook"}


def request_user(request: Request) -> User | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    user_id = decode_session_token(token)
    if not user_id:
        return None
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.is_active:
            return None
        db.expunge(user)
        return user


@app.middleware("http")
async def auth_and_csrf_middleware(request: Request, call_next):
    path = request.url.path
    user = request_user(request)
    request.state.user = user

    if path == "/app" or path.startswith("/app/"):
        if not user:
            return RedirectResponse("/login", status_code=303)

    if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
        if not user:
            return JSONResponse({"detail": "Требуется вход"}, status_code=401)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and user.role == "viewer":
            return JSONResponse({"detail": "Режим только для просмотра"}, status_code=403)

    if request.method not in {"GET", "HEAD", "OPTIONS"} and path.startswith("/api/"):
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        if origin and urlparse(origin).netloc != host:
            return JSONResponse({"detail": "Недопустимый источник запроса"}, status_code=403)

    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "provider": settings.image_provider, "queue": settings.queue_mode}


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    return (STATIC_DIR / "landing.html").read_text(encoding="utf-8")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request_user(request):
        return RedirectResponse("/app", status_code=303)
    return (STATIC_DIR / "login.html").read_text(encoding="utf-8")


@app.get("/app", response_class=HTMLResponse)
def studio() -> str:
    return (STATIC_DIR / "app.html").read_text(encoding="utf-8")


def render_public_workspace(workspace: Workspace) -> str:
    display_name = escape(workspace.display_name)
    tagline = escape(workspace.tagline)
    slug = escape(workspace.slug)
    return f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"/><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>
<title>{display_name}</title><link rel=\"stylesheet\" href=\"/static/styles.css\"/><script src=\"/static/theme.js\"></script></head>
<body><div class=\"public-page\"><main class=\"public-card\"><div class=\"brand-mark\">AI</div><span class=\"public-slug\">/{slug}</span>
<h1>{display_name}</h1><p>{tagline}</p><div class=\"hero-actions\" style=\"justify-content:center\"><a class=\"button primary\" href=\"/login\">Войти</a></div></main></div></body></html>"""


@app.get("/{slug}", response_class=HTMLResponse)
def public_workspace(slug: str, db: Session = Depends(get_db)) -> str:
    if slug in {"api", "static", "login", "app", "health", "docs", "redoc", "openapi.json"}:
        raise HTTPException(404)
    workspace = db.scalar(select(Workspace).where(Workspace.slug == slug, Workspace.is_public.is_(True)))
    if not workspace:
        raise HTTPException(404, "Публичное пространство не найдено")
    return render_public_workspace(workspace)
