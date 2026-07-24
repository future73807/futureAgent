"""
futureAgent 启动入口
整合: FastAPI + LangGraph + LiteLLM + MCP + Casbin
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import router
from config import settings
from core.observability import install_observability
from db.database import init_db
import os


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="futureAgent",
    description="模块化 AI Agent 框架 - 基于开源轮子拼装",
    version="0.1.0",
    swagger_ui_parameters={"tryItOutEnabled": True},
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Workspace-ID"],
)
install_observability(app)

app.include_router(router, prefix="/api")

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
