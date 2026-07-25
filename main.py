"""
futureAgent 启动入口
整合: FastAPI + LangGraph + LiteLLM + MCP + Casbin + 汇报智能体
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from api.docs_catalog import render_api_catalog
from api.openapi import API_TITLE, build_openapi_schema
from api.routes import router
from api.report_routes import router as report_router
from config import settings
from core.observability import install_observability
from db.database import init_db
import os


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield

app = FastAPI(
    title=API_TITLE,
    description="面向 futureAgent 的中文开放接口文档。",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


def custom_openapi() -> dict:
    return build_openapi_schema(app)


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Workspace-ID"],
)
install_observability(app)

app.include_router(router, prefix="/api")
app.include_router(report_router, prefix="/api/v1/report")


def _root_path(request: Request, path: str) -> str:
    return f"{request.scope.get('root_path', '').rstrip('/')}{path}"


def _documentation_response(request: Request, *, detailed: bool) -> HTMLResponse:
    content = render_api_catalog(
        app.openapi(),
        openapi_url=_root_path(request, app.openapi_url or "/openapi.json"),
        compact_catalog_url=_root_path(request, "/docs"),
        detailed_catalog_url=_root_path(request, "/redoc"),
        detailed=detailed,
    )
    return HTMLResponse(
        content=content,
        headers={
            "Content-Language": "zh-CN",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/docs", include_in_schema=False)
async def api_documentation_catalog(request: Request) -> HTMLResponse:
    """提供由当前 OpenAPI schema 生成的中文接口目录。"""
    return _documentation_response(request, detailed=False)


@app.get("/redoc", include_in_schema=False)
async def complete_api_documentation_catalog(request: Request) -> HTMLResponse:
    """提供含完整 JSON Schema 的中文接口目录。"""
    return _documentation_response(request, detailed=True)

# 挂载静态文件目录
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    """返回自定义 Dashboard"""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {
        "service": "futureAgent",
        "docs": "/docs",
        "version": "0.1.0",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
