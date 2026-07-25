"""
ModelHub - 基于 LiteLLM 的统一模型切换层
开源轮子: https://github.com/BerriAI/litellm
"""
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

from config import settings

try:
    import litellm
    from litellm import acompletion
    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False


class ModelHub:
    """
    利用 LiteLLM 统一了不同模型的调用方式
    model_id 例如: "gpt-4o", "claude-3-5-sonnet", "ollama/llama3"
    """

    def __init__(self):
        if LITELLM_AVAILABLE:
            litellm.set_verbose = False
            if settings.openai_api_key:
                litellm.openai_key = settings.openai_api_key
            if settings.anthropic_api_key:
                litellm.anthropic_key = settings.anthropic_api_key
            if settings.google_api_key:
                litellm.gemini_key = settings.google_api_key

    async def generate(
        self,
        model_id: str,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        stream: bool = False,
    ):
        """LiteLLM 统一调用接口"""
        if not LITELLM_AVAILABLE:
            raise ImportError("未安装 LiteLLM，请先安装 API 依赖。")
        request_model = model_id
        if settings.litellm_proxy_url:
            # LiteLLM Proxy 暴露 OpenAI 兼容接口；openai/ 前缀让本地 LiteLLM
            # 客户端把模型名原样交给 Proxy，由后台配置决定真实提供商。
            request_model = f"openai/{model_id}"
            kwargs = {
                "api_base": self._proxy_base_url(),
                "api_key": settings.litellm_master_key,
            }
        else:
            kwargs = self._provider_kwargs(model_id)
        response = await acompletion(
            model=request_model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            stream=stream,
            **kwargs,
        )
        return response

    def get_chat_model(
        self,
        model_id: Optional[str] = None,
        temperature: float = 0,
        streaming: bool = True,
        **kwargs,
    ) -> BaseChatModel:
        """
        获取 LangChain 兼容的 ChatModel
        用于接入 LangGraph 的 create_react_agent
        """
        model = model_id or settings.default_model
        if settings.litellm_proxy_url:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                streaming=streaming,
                api_key=settings.litellm_master_key,
                base_url=self._proxy_base_url(),
                **kwargs,
            )
        provider_kwargs = self._provider_kwargs(model)
        provider_kwargs.update(kwargs)
        if LITELLM_AVAILABLE:
            from langchain_community.chat_models import ChatLiteLLM
            return ChatLiteLLM(
                model=model,
                temperature=temperature,
                streaming=streaming,
                **provider_kwargs,
            )
        else:
            # 后备方案: 使用 langchain-openai
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                streaming=streaming,
                api_key=settings.openai_api_key,
                base_url=provider_kwargs.pop("api_base", settings.openai_base_url),
                **provider_kwargs,
            )

    @staticmethod
    def _proxy_base_url() -> str:
        base_url = settings.litellm_proxy_url.rstrip("/")
        return base_url if base_url.endswith("/v1") else f"{base_url}/v1"

    @staticmethod
    def _provider_kwargs(model_id: str) -> dict:
        if model_id.startswith("ollama/"):
            return {"api_base": settings.ollama_base_url}
        if model_id.startswith(("gpt-", "openai/")) and settings.openai_base_url:
            return {"api_base": settings.openai_base_url}
        return {}

    @staticmethod
    def _is_usable_credential(value: str) -> bool:
        """Reject the example values that make a route look falsely usable.

        A copied ``.env.example`` intentionally contains readable placeholder
        values.  They must not be treated as provider credentials: otherwise
        a direct chat request gets as far as an SSE stream and only fails after
        the UI appears to have started working.
        """
        candidate = (value or "").strip()
        normalized = candidate.lower()
        if not candidate:
            return False
        placeholders = {
            "sk-your-openai-key",
            "your-google-api-key",
            "replace-with-a-long-random-secret",
            "change-this-development-secret-before-production",
        }
        return normalized not in placeholders and not normalized.startswith(
            ("sk-your-", "your-", "replace-with-")
        )

    @classmethod
    def is_direct_provider_configured(cls, model_id: str) -> bool:
        """Return whether the API itself has a usable direct provider route."""
        if model_id.startswith(("gpt-", "openai/")):
            return cls._is_usable_credential(settings.openai_api_key)
        if model_id.startswith("claude"):
            return cls._is_usable_credential(settings.anthropic_api_key)
        if model_id.startswith(("gemini/", "gemini-")):
            return cls._is_usable_credential(settings.google_api_key)
        if model_id.startswith("ollama/"):
            return bool(settings.ollama_base_url.strip())
        return False

    @classmethod
    def is_model_configured(cls, model_id: str) -> bool:
        """Return whether a request has an application-level route.

        A LiteLLM proxy is a configured route, not evidence that a particular
        upstream provider can answer.  Callers that present status to an
        operator should use :meth:`configuration_source` so they can make that
        distinction visible.
        """
        return bool(settings.litellm_proxy_url.strip()) or cls.is_direct_provider_configured(model_id)

    @classmethod
    def configuration_source(cls, model_id: str) -> str:
        if settings.litellm_proxy_url.strip():
            return "litellm_proxy"
        if cls.is_direct_provider_configured(model_id):
            return "direct_provider"
        return "missing"

    @staticmethod
    def readiness_error(model_id: str) -> str | None:
        """Return a stable pre-flight failure before opening an SSE stream.

        A configured key still cannot prove that a remote provider is healthy,
        but this removes the two avoidable failures of the old demo: starting a
        successful-looking stream without LiteLLM installed, and attempting a
        cloud provider call without any credential.
        """
        if settings.litellm_proxy_url.strip():
            return None
        if not LITELLM_AVAILABLE:
            return "未安装 LiteLLM，请先安装 API 依赖后再使用 AI 对话。"
        if not ModelHub.is_model_configured(model_id):
            return f"模型“{model_id}”尚未配置。请添加供应商凭据或配置 LiteLLM 内部网关。"
        return None

    @staticmethod
    def list_supported_models() -> list[str]:
        """列出常用支持的模型"""
        return [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-3.5-turbo",
            "claude-3-5-sonnet-20241022",
            "claude-3-haiku-20240307",
            "ollama/llama3",
            "ollama/qwen2.5",
            "gemini/gemini-1.5-pro",
            "gemini/gemini-1.5-flash",
        ]
