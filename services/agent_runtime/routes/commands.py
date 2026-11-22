"""Composer helpers: slash commands and workspace file mentions.

The file list reuses the workspace ``glob`` tool, so the picker sees exactly
the tree the agent can read, with heavy build directories filtered out.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from flare_common.config import Settings
from tools_gateway.builtin import create_default_registry
from tools_gateway.registry import ToolRegistry

COMMANDS: list[dict[str, str]] = [
    {"name": "clear", "description": "Clear conversation"},
    {"name": "model", "description": "Switch model"},
]

IGNORED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    "data",
    ".data",
}
MAX_FILES = 300


@lru_cache(maxsize=4)
def _registry(root: str) -> ToolRegistry:
    return create_default_registry(workspace=root)


def _workspace_root(settings: Settings) -> Path:
    return Path(settings.workspace_dir or os.getcwd()).resolve()


def _ignored(relative: str) -> bool:
    return any(part in IGNORED_PARTS for part in relative.split("/"))


async def list_workspace_files(settings: Settings) -> list[str]:
    root = _workspace_root(settings)
    paths: list[str] = []
    result = await _registry(str(root)).execute("glob", {"pattern": "**/*"})
    if result.ok:
        for match in result.artifacts.get("matches", []):
            relative = str(match).replace("\\", "/")
            if not _ignored(relative) and relative not in paths:
                paths.append(relative)
    # The tool caps matches; top the picker up with a bounded directory walk.
    if len(paths) < 25:
        for path in sorted(root.rglob("*")):
            if len(paths) >= MAX_FILES:
                break
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if _ignored(relative) or relative in paths:
                continue
            paths.append(relative)
    return paths[:MAX_FILES]


def build_commands_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["composer"])

    @router.get("/commands")
    async def commands() -> list[dict[str, str]]:
        return COMMANDS

    @router.get("/workspaces/files")
    async def workspace_files() -> dict[str, Any]:
        files = await list_workspace_files(settings)
        return {"root": _workspace_root(settings).name, "files": files, "count": len(files)}

    return router
