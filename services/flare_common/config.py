"""全局配置（12-factor：全部来自环境变量，前缀 FLARE_）。

示例：FLARE_ENV / FLARE_DATABASE_URL / FLARE_MODEL_PROVIDER
extra="forbid"：拼错的环境变量在启动即报错，绝不静默沿用默认值（fail-fast）。
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# One .env for local and container runs: it has to reach os.environ so
# DATABASE_URL and provider-native keys (OPENAI_API_KEY, DEEPSEEK_API_KEY)
# resolve the same way real environment variables do. Existing variables win.
# Tests set FLARE_SKIP_DOTENV so a developer's .env cannot leak into the suite.
_SKIP_DOTENV = os.environ.get("FLARE_SKIP_DOTENV", "").strip().lower() in {"1", "true", "yes"}
if not _SKIP_DOTENV:
    load_dotenv()


class Settings(BaseSettings):
    """应用配置。env_file=.env 仅在本地开发加载；生产全部走环境变量。"""

    model_config = SettingsConfigDict(
        env_prefix="FLARE_",
        env_file=None if _SKIP_DOTENV else ".env",
        extra="forbid",
        populate_by_name=True,
    )

    app_name: str = "flare-agent"
    env: str = "dev"
    log_level: str = "INFO"

    # CORS：dev 默认放开；生产用 JSON 数组，如 FLARE_CORS_ORIGINS='["https://app.example.com"]'
    cors_origins: list[str] = ["*"]

    # DATABASE_URL (no prefix) is the deployment standard; both names work.
    database_url: str = Field(
        default="postgresql://flare:flare@localhost:5432/flare",
        validation_alias=AliasChoices("DATABASE_URL", "FLARE_DATABASE_URL"),
    )
    redis_url: str = "redis://localhost:6379/0"

    object_store_endpoint: str = "http://localhost:9000"
    object_store_access_key: str = "minioadmin"
    object_store_secret_key: str = "minioadmin"

    # 供应商：openai | anthropic（Claude 原生）；openai 兼容 DashScope/DeepSeek/vLLM
    # mock 仅用于测试：显式设置 FLARE_MODEL_PROVIDER=mock 才会启用
    model_provider: str = "openai"
    model_api_key: str = ""
    model_base_url: str = "https://api.openai.com/v1"
    model_name: str = "gpt-4o-mini"
    # 模型设置页（控制台「模型」）本地持久化位置；真实环境变量优先于该文件
    model_config_path: str = "data/model_config.json"

    # 供应商原生变量：既接受无前缀名（OPENAI_API_KEY / DEEPSEEK_*），
    # 也接受 FLARE_ 前缀；声明成字段后 .env 里的这些行不会被 extra=forbid 拒绝。
    openai_api_key: str = Field(
        default="", validation_alias=AliasChoices("OPENAI_API_KEY", "FLARE_OPENAI_API_KEY")
    )
    openai_base_url: str = Field(
        default="", validation_alias=AliasChoices("OPENAI_BASE_URL", "FLARE_OPENAI_BASE_URL")
    )
    deepseek_api_key: str = Field(
        default="", validation_alias=AliasChoices("DEEPSEEK_API_KEY", "FLARE_DEEPSEEK_API_KEY")
    )
    deepseek_base_url: str = Field(
        default="", validation_alias=AliasChoices("DEEPSEEK_BASE_URL", "FLARE_DEEPSEEK_BASE_URL")
    )
    deepseek_model: str = Field(
        default="", validation_alias=AliasChoices("DEEPSEEK_MODEL", "FLARE_DEEPSEEK_MODEL")
    )

    # M5：任务存储（memory|sqlite|redis）；OTel 导出端点（空=不启用）
    # DSH 对齐：本地默认 sqlite 落盘（data/tasks.sqlite3）——会话列表重启可查；
    # 生产多实例用 redis（FLARE_TASK_STORE=redis）
    task_store: str = "sqlite"
    otel_endpoint: str = ""

    # M6：SLO 目标（错误预算/告警依据；生产用环境变量覆盖，如 FLARE_SLO_AVAILABILITY=0.99）
    slo_availability: float = 0.99
    slo_p95_latency_seconds: float = 5.0
    slo_period_days: int = 30

    # FR-2/FR-3：MCP 服务器列表（JSON）+ 技能库目录
    # FLARE_MCP_SERVERS='[{"name":"echo","url":"http://localhost:9001/mcp","transport":"streamable_http","headers":{},"enabled":true}]'
    mcp_servers: list[dict] = []
    skills_dir: str = "data/skills"

    # F9.3：OpenAI 兼容 API 认证（FLARE_API_KEY；空=不校验，生产务必配置）
    api_key: str = ""

    # Harness 工具的工作目录（read/write/edit/glob/grep/bash 绑定到这里）
    workspace_dir: str = ""

    # 登录门禁：Landing + Google OAuth（配置了 session_secret 即启用）
    auth_required: bool | None = None
    session_secret: str = ""
    session_ttl_hours: int = 168
    google_client_id: str = ""
    google_client_secret: str = ""
    app_base_url: str = "http://127.0.0.1:8000"
    auth_allow_local: bool = False

    # 语音回复（TTS）：OpenAI 兼容 speech 端点（本地默认 Kokoro，端口 8023）
    tts_enabled: bool = True
    tts_url: str = "http://127.0.0.1:8023/v1/audio/speech"
    tts_voice: str = "af_bella"
    tts_speed: float = 0.88
    tts_timeout: float = 90.0
    tts_rate_per_minute: int = 30

    # 安全加固：响应头 / 请求体上限 / 限流 / 文档暴露（None=按环境取默认）
    security_headers: bool = True
    max_request_bytes: int = 25 * 1024 * 1024
    rate_limit_enabled: bool | None = None
    rate_limit_per_minute: int = 120
    rate_limit_chat_per_minute: int = 20
    rate_limit_trust_proxy: bool = False
    docs_enabled: bool | None = None
    # 可选：整站 HTTP Basic 认证（生产请置于 TLS 之后；空=不启用）
    ui_auth_username: str = ""
    ui_auth_password: str = ""

    # F1.3/F2.4：审批策略（等于或高于该级别的工具需人工审批；默认 destructive 起）
    # 例如 FLARE_APPROVAL_REQUIRE_LEVEL=write 则所有写/破坏性工具都要审批
    approval_require_level: str = "destructive"
    approval_timeout: float = 300.0  # 审批等待超时（秒），超时自动按拒绝处理
    # 审批后端：local（进程内，默认/单实例）| redis（多实例共享，跨节点决策轮询唤醒）
    approval_backend: str = "local"
    # TOFU（首用信任）：同作用域某工具获批一次后后续自动放行，防审批疲劳
    approval_tofu: bool = True
    approval_tofu_scope: str = "thread"  # thread（会话线程，默认）| tenant | off

    @model_validator(mode="after")
    def _resolve_model_credentials(self) -> "Settings":
        """Accept provider-native keys so a real model needs no FLARE_* rename.

        `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` (and optional `*_BASE_URL`) fill the
        gateway config; an explicit FLARE_MODEL_API_KEY/provider always wins.
        """
        if self.model_api_key:
            return self
        deepseek_key = self.deepseek_api_key.strip()
        openai_key = self.openai_api_key.strip()
        if deepseek_key:
            self.model_api_key = deepseek_key
            if self.model_provider == "mock":
                self.model_provider = "openai"
            if self.deepseek_base_url.strip():
                self.model_base_url = self.deepseek_base_url.strip()
            elif "deepseek" not in self.model_base_url.lower():
                self.model_base_url = "https://api.deepseek.com/v1"
            if self.deepseek_model.strip():
                self.model_name = self.deepseek_model.strip()
            elif self.model_name == "gpt-4o-mini":
                self.model_name = "deepseek-chat"
        elif openai_key:
            self.model_api_key = openai_key
            if self.model_provider == "mock":
                self.model_provider = "openai"
            if self.openai_base_url.strip():
                self.model_base_url = self.openai_base_url.strip()
            elif self.model_base_url == "http://localhost:9001/v1":
                self.model_base_url = "https://api.openai.com/v1"
        return self


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置。"""
    return Settings()
