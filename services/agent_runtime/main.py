"""Agent Runtime 入口：make dev / uvicorn 从这里启动。

create_app() 保持纯 API（可测）；Web 构建产物(services/web/dist)在此挂到根路径，
未构建时则纯 API 模式（前端走 Vite dev 代理）。路径挂载放最后，避免遮蔽 API 路由。
知识库在 main 里落盘到 data/kb.sqlite3（跨重启复用；测试仍走内存库）。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent_runtime.app import create_app
from memory.memory import MemoryManager
from rag.pipeline import KnowledgeBase
from rag.store import SqliteVectorStore

_kb_path = Path(__file__).resolve().parents[1] / "data" / "kb.sqlite3"
_mem_path = Path(__file__).resolve().parents[1] / "data" / "memory.sqlite3"
_mem_vec_path = Path(__file__).resolve().parents[1] / "data" / "memory_vec.sqlite3"
_kb_path.parent.mkdir(parents=True, exist_ok=True)

app = create_app(
    knowledge_base=KnowledgeBase(store=SqliteVectorStore(str(_kb_path))),
    memory=MemoryManager(str(_mem_path), vector_store=SqliteVectorStore(str(_mem_vec_path))),
)


class SpaStaticFiles(StaticFiles):
    """Serve the SPA shell for unknown paths; API paths keep honest 404s."""

    async def get_response(self, path, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            request_path = scope.get("path", "")
            if request_path.startswith(("/api/", "/v1/", "/mcp")):
                raise
            return await super().get_response("index.html", scope)


# Docker copies the build to /app/static and sets FLARE_WEB_DIST; a local
# `npm run build` is picked up from services/web/dist with no configuration.
_web_dist = Path(
    os.environ.get("FLARE_WEB_DIST") or (Path(__file__).resolve().parents[1] / "web" / "dist")
)
if _web_dist.is_dir():
    app.mount("/", SpaStaticFiles(directory=str(_web_dist), html=True), name="web")
