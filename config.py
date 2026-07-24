import json
from pathlib import Path

from pydantic import PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    # ===== LiteLLM 模型配置 =====
    default_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str = ""
    google_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # ===== LiteLLM Proxy =====
    litellm_proxy_url: str = ""
    litellm_master_key: str = "sk-futureagent"

    # ===== 应用身份与数据 =====
    database_url: str = f"sqlite:///{(BASE_DIR / 'futureagent.db').as_posix()}"
    jwt_secret_key: str = "change-this-development-secret-before-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12
    refresh_token_expire_days: int = 14
    bootstrap_admin_email: str = "admin@futureagent.dev"
    bootstrap_admin_password: str = "ChangeMe123!"
    upload_dir: str = str(BASE_DIR / "uploads")
    max_upload_mb: int = 20
    # A governed work run must have bounded resource use.  These limits are
    # deliberately applied server-side, rather than trusting a browser timer.
    agent_run_timeout_seconds: int = 180
    max_concurrent_agent_runs_per_workspace: int = 2
    storage_backend: str = "local"
    storage_s3_bucket: str = ""
    storage_s3_endpoint_url: str = ""
    storage_s3_region: str = "us-east-1"
    storage_s3_access_key_id: str = ""
    storage_s3_secret_access_key: str = ""
    storage_s3_prefix: str = "futureagent"
    storage_s3_addressing_style: str = "auto"
    run_migrations_on_startup: bool = False
    metrics_bearer_token: str = ""
    cors_origins_csv: str = "http://localhost:5173,http://localhost:5174"

    # ===== MCP 配置 =====
    mcp_server_port: int = 8050
    mcp_hostnames_csv: str = "localhost"
    mcp_servers_json: str = ""
    mcp_connect_timeout: float = 5.0
    enable_local_mcp_tools: bool = False

    # ===== 数据库配置 =====
    postgres_dsn: PostgresDsn = (
        "postgresql://postgres:password@localhost:5432/postgres"
    )

    @computed_field
    @property
    def orm_conn_str(self) -> str:
        return self.postgres_dsn.encoded_string().replace(
            "postgresql://", "postgresql+psycopg://"
        )

    @computed_field
    @property
    def checkpoint_conn_str(self) -> str:
        return self.postgres_dsn.encoded_string()

    # ===== Langfuse 可观测性 =====
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # ===== Casbin 权限 =====
    casbin_model_path: str = str(BASE_DIR / "auth" / "rbac_model.conf")
    casbin_policy_path: str = str(BASE_DIR / "auth" / "rbac_policy.csv")

    # ===== Skill 配置 =====
    skills_dir: str = str(BASE_DIR / "skills")

    environment: str = "development"

    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        return [
            value.strip().rstrip("/")
            for value in self.cors_origins_csv.split(",")
            if value.strip()
        ]

    @computed_field
    @property
    def mcp_hostnames(self) -> list[str]:
        return [
            h.strip() for h in self.mcp_hostnames_csv.split(",") if h.strip()
        ]

    @computed_field
    @property
    def mcp_servers(self) -> dict[str, str]:
        """返回 MCP 服务名到 SSE 地址的映射。

        ``MCP_SERVERS_JSON`` 可用于给服务设置稳定名称，例如：
        ``{"local_tools":"http://localhost:8050/mcp"}``。未配置时继续兼容
        ``MCP_HOSTNAMES_CSV``。
        """
        if self.mcp_servers_json.strip():
            try:
                raw_servers = json.loads(self.mcp_servers_json)
            except json.JSONDecodeError as exc:
                raise ValueError("MCP_SERVERS_JSON 必须是合法的 JSON 对象") from exc
            if not isinstance(raw_servers, dict):
                raise ValueError("MCP_SERVERS_JSON 必须是服务名到地址的 JSON 对象")
            return {
                str(name): self._normalize_mcp_url(str(url))
                for name, url in raw_servers.items()
            }

        return {
            hostname: self._normalize_mcp_url(hostname)
            for hostname in self.mcp_hostnames
        }

    def _normalize_mcp_url(self, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            value = f"http://{value}:{self.mcp_server_port}"
        if not value.endswith(("/mcp", "/sse")):
            value = f"{value}/mcp"
        return value


settings = Settings()
