"""Composer helper endpoints: slash commands and workspace files."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_runtime.routes.commands import build_commands_router
from flare_common.config import Settings


def _client(tmp_path: Path) -> TestClient:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text("export default null;\n")
    (tmp_path / "README.md").write_text("# demo\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("x")
    settings = Settings(_env_file=None, env="test", workspace_dir=str(tmp_path))
    app = FastAPI()
    app.include_router(build_commands_router(settings))
    return TestClient(app)


def test_commands_endpoint(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/v1/commands")
    assert response.status_code == 200
    assert response.json() == [
        {"name": "clear", "description": "Clear conversation"},
        {"name": "model", "description": "Switch model"},
    ]


def test_workspace_files_are_relative_and_filtered(tmp_path: Path) -> None:
    payload = _client(tmp_path).get("/v1/workspaces/files").json()
    assert payload["count"] == len(payload["files"])
    assert payload["root"] == tmp_path.name
    assert "README.md" in payload["files"]
    assert "src/App.tsx" in payload["files"]
    assert all(not path.startswith("/") for path in payload["files"])
    assert not any("node_modules" in path for path in payload["files"])
