"""pytest 全局配置：测试环境隔离。

- FLARE_TASK_STORE=memory：测试默认不落盘（避免默认 sqlite 写 data/tasks.sqlite3
  污染真实数据 + 测试间串扰）。真实服务（uvicorn / make dev）仍用 sqlite 默认 → 会话持久。
"""

from __future__ import annotations

import os

import pytest

# Must run before any test module imports flare_common.config: the suite must
# never inherit a developer's .env (production env, database URL, real keys).
os.environ["FLARE_SKIP_DOTENV"] = "1"
os.environ["FLARE_ENV"] = "test"
os.environ["FLARE_TASK_STORE"] = "memory"
os.environ["FLARE_RATE_LIMIT_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def _isolate_task_store() -> None:
    os.environ["FLARE_TASK_STORE"] = "memory"
    yield
