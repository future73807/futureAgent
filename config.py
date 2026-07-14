from pydantic import PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    # ===== LiteLLM 模型配置 =====
    default_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # ===== MCP 配置 =====
    mcp_server_port: int = 8050
    mcp_hostnames_csv: str = "mcp"

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
    casbin_model_path: str = "auth/rbac_model.conf"
    casbin_policy_path: str = "auth/rbac_policy.csv"

    environment: str = "development"

    @computed_field
    @property
    def mcp_hostnames(self) -> list[str]:
        return [
            h.strip() for h in self.mcp_hostnames_csv.split(",") if h.strip()
        ]


settings = Settings()
