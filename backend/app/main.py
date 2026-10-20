"""FastAPI 应用入口：认证、路由、统一异常包与前端静态托管。"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import CORS_ORIGINS, FRONTEND_DIST
from .database import SessionLocal, init_db
from .errors import ApiError, ok
from .routers import (
    auth,
    backup,
    bookmarks,
    categories,
    crawl,
    export,
    graph,
    health,
    imports,
    knowledge,
    mistakes,
    pending,
    practice,
    questions,
    ratings,
    review,
    stats,
    tags,
)
from .routers import (
    settings as settings_router,
)
from .security import ensure_default_user
from .services.crawler import mark_running_tasks_failed
from .services.tagging import load_seed_rules

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("bajiu")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    ensure_default_user()
    db = SessionLocal()
    try:
        load_seed_rules(db)
    finally:
        db.close()
    mark_running_tasks_failed()
    logger.info("八股文智能复习系统启动完成")
    yield


app = FastAPI(
    title="八股文智能复习系统",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            {"code": exc.code, "data": exc.data, "message": exc.message}
        ),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content=jsonable_encoder(
            {
                "code": "VALIDATION_ERROR",
                "data": {"errors": exc.errors()},
                "message": "参数校验失败",
            }
        ),
    )


_STATUS_CODE_MAP = {
    400: "VALIDATION_ERROR",
    401: "AUTH_REQUIRED",
    403: "AUTH_REQUIRED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_request: Request, exc: StarletteHTTPException):
    code = _STATUS_CODE_MAP.get(exc.status_code, "INTERNAL_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "data": None, "message": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("未处理异常 request_id=%s: %s", request_id, exc)
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "data": {"request_id": request_id},
            "message": "服务器内部错误",
        },
    )


API_PREFIX = "/api/v1"
for router in (
    health.router,
    auth.router,
    categories.router,
    tags.router,
    questions.router,
    knowledge.router,
    imports.router,
    pending.router,
    practice.router,
    review.router,
    ratings.router,
    mistakes.router,
    bookmarks.router,
    stats.router,
    crawl.router,
    graph.router,
    settings_router.router,
    export.router,
    backup.router,
):
    app.include_router(router, prefix=API_PREFIX)


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        if full_path.startswith(("api/", "docs", "openapi")):
            raise ApiError(404, "NOT_FOUND", "资源不存在")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    def root():
        return ok(
            {
                "message": "前端尚未构建。开发模式请运行 npm run dev；或执行 npm run build。",
                "docs": "/api/docs",
                "health": "/api/v1/healthz",
            }
        )
