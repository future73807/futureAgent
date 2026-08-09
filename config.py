import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
    longcat_api_key: str = ""
    longcat_api_base: str = "https://api.longcat.chat/openai"

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
    cors_origins_csv: str = "http://localhost:5173,http://localhost:5174,http://localhost:8081,http://localhost:8082"

    # ===== MCP 配置 =====
    mcp_server_port: int = 8050
    mcp_hostnames_csv: str = "localhost"
    mcp_servers_json: str = ""
    mcp_connect_timeout: float = 5.0
    enable_local_mcp_tools: bool = False
    # Shared by the API and the bundled MCP service.  It authenticates the
    # server-derived workspace scope attached to local file-tool sessions; it
    # is not exposed to the model or browser.
    mcp_workspace_signing_key: str = (
        "change-this-development-mcp-secret-before-production"
    )

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
            servers: dict[str, str] = {}
            for raw_name, raw_url in raw_servers.items():
                name = str(raw_name).strip()
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
                    raise ValueError(
                        "MCP 服务名必须以字母开头，且只能包含字母、数字、下划线和连字符"
                    )
                if name in servers:
                    raise ValueError(f"MCP 服务名重复：{name}")
                servers[name] = self._normalize_mcp_url(str(raw_url))
            return servers

        return {
            hostname: self._normalize_mcp_url(hostname)
            for hostname in self.mcp_hostnames
        }

    def _normalize_mcp_url(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("MCP 服务地址不能为空")

        has_scheme = value.startswith(("http://", "https://"))
        if "://" in value and not has_scheme:
            raise ValueError("MCP 服务地址只允许 HTTP 或 HTTPS")
        candidate = value if has_scheme else f"http://{value}"
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MCP 服务地址必须是有效的 HTTP 或 HTTPS URL")
        try:
            explicit_port = parsed.port
        except ValueError as exc:
            raise ValueError("MCP 服务地址端口无效") from exc

        netloc = parsed.netloc
        if not has_scheme and explicit_port is None:
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            netloc = f"{host}:{self.mcp_server_port}"
        path = parsed.path.rstrip("/")
        if not path.endswith(("/mcp", "/sse")):
            path = f"{path}/mcp"
        return urlunsplit((parsed.scheme, netloc, path, parsed.query, ""))


settings = Settings()
