"""
ModelHub - 基于 LiteLLM 的统一模型切换层
开源轮子: https://github.com/BerriAI/litellm
"""
import time
from typing import Optional

import httpx

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
    model_id 例如: "gpt-4o", "claude-3-5-sonnet", "ollama/llama3", "LongCat-2.0"
    """

    _ollama_models_cache: dict[str, tuple[float, set[str] | None]] = {}
    _ollama_cache_ttl_seconds = 5.0

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
        """统一调用接口 - 优先使用 LiteLLM，否则用 langchain-openai"""
        provider_kwargs = self._provider_kwargs(model_id)
        
        # 如果没有 LiteLLM，使用 langchain-openai 作为后备
        if not LITELLM_AVAILABLE:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
            
            llm = ChatOpenAI(
                model=model_id,
                temperature=temperature,
                streaming=stream,
                api_key=provider_kwargs.get("api_key"),
                base_url=provider_kwargs.get("api_base"),
            )
            
            lc_messages = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    lc_messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    lc_messages.append(AIMessage(content=content))
                elif role == "system":
                    lc_messages.append(SystemMessage(content=content))
            
            if stream:
                async def stream_gen():
                    async for chunk in llm.astream(lc_messages):
                        class FakeChoice:
                            def __init__(self, content):
                                self.delta = type('Delta', (), {'content': content})()
                        yield type('Response', (), {'choices': [FakeChoice(chunk.content)]})()
                return stream_gen()
            else:
                response = await llm.ainvoke(lc_messages)
                class FakeChoice:
                    def __init__(self, content):
                        self.delta = type('Delta', (), {'content': content})()
                        self.message = type('Message', (), {'content': content})()
                return type('Response', (), {'choices': [FakeChoice(response.content)]})()
        
        # 有 LiteLLM 时使用 LiteLLM
        request_model = self._litellm_model_name(model_id)
        if settings.litellm_proxy_url:
            request_model = f"openai/{model_id}"
            kwargs = {
                "api_base": self._proxy_base_url(),
                "api_key": settings.litellm_master_key,
            }
        else:
            kwargs = provider_kwargs
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
                model=self._litellm_model_name(model),
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
                api_key=provider_kwargs.get("api_key", settings.openai_api_key),
                base_url=provider_kwargs.pop("api_base", settings.openai_base_url),
                **provider_kwargs,
            )

    @staticmethod
    def _proxy_base_url() -> str:
        base_url = settings.litellm_proxy_url.rstrip("/")
        return base_url if base_url.endswith("/v1") else f"{base_url}/v1"

    @staticmethod
    def _provider_kwargs(model_id: str) -> dict:
        model_lower = model_id.lower()
        if model_lower.startswith("ollama/"):
            return {"api_base": settings.ollama_base_url}
        if model_lower.startswith(("gpt-", "openai/")) and settings.openai_base_url:
            return {"api_base": settings.openai_base_url}
        if model_lower.startswith("longcat") and settings.longcat_api_key:
            return {"api_base": settings.longcat_api_base, "api_key": settings.longcat_api_key}
        return {}

    @staticmethod
    def _litellm_model_name(model_id: str) -> str:
        """Route OpenAI-compatible providers through LiteLLM explicitly.

        LongCat exposes an OpenAI-compatible API, but its public model name
        does not identify a provider to LiteLLM.  Without the prefix LiteLLM
        rejects the request before it reaches the configured API base.
        """
        if model_id.lower().startswith("longcat"):
            return f"openai/{model_id}"
        return model_id

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
        model_lower = model_id.lower()
        if model_lower.startswith(("gpt-", "openai/")):
            return cls._is_usable_credential(settings.openai_api_key)
        if model_lower.startswith("claude"):
            return cls._is_usable_credential(settings.anthropic_api_key)
        if model_lower.startswith(("gemini/", "gemini-")):
            return cls._is_usable_credential(settings.google_api_key)
        if model_lower.startswith("ollama/"):
            return bool(settings.ollama_base_url.strip())
        if model_lower.startswith("longcat"):
            return cls._is_usable_credential(settings.longcat_api_key)
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
    def _available_ollama_models(cls) -> set[str] | None:
        """Return locally installed model names, or ``None`` when unreachable.

        A configured URL is not runtime readiness. The short cache keeps the
        model picker responsive while allowing a newly started Ollama service
        to become available without restarting futureAgent.
        """
        base_url = settings.ollama_base_url.strip().rstrip("/")
        if not base_url:
            return None
        root_url = base_url[:-3] if base_url.endswith("/v1") else base_url
        now = time.monotonic()
        cached = cls._ollama_models_cache.get(root_url)
        if cached and now - cached[0] < cls._ollama_cache_ttl_seconds:
            return cached[1]
        available: set[str] | None = None
        try:
            with httpx.Client(timeout=0.75, trust_env=False) as client:
                response = client.get(f"{root_url}/api/tags")
                response.raise_for_status()
                payload = response.json()
            available = set()
            for item in payload.get("models", []) if isinstance(payload, dict) else []:
                if not isinstance(item, dict):
                    continue
                for key in ("name", "model"):
                    value = str(item.get(key) or "").strip().lower()
                    if value:
                        available.add(value)
                        available.add(value.split(":", 1)[0])
        except (httpx.HTTPError, ValueError, TypeError):
            available = None
        cls._ollama_models_cache[root_url] = (now, available)
        return available

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
            # 没有 LiteLLM 时，如果有直接供应商凭据，也允许通过
            if ModelHub.is_direct_provider_configured(model_id):
                return None
            return "未安装 LiteLLM，请先安装 API 依赖后再使用 AI 对话。"
        if model_id.lower().startswith("ollama/"):
            available = ModelHub._available_ollama_models()
            if available is None:
                return "Ollama 服务当前不可达，请先启动本地 Ollama 后再使用该模型。"
            requested = model_id.split("/", 1)[1].lower().split(":", 1)[0]
            if requested not in available:
                return f"Ollama 中尚未安装模型“{requested}”，请先拉取该模型。"
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
            "LongCat-2.0",
        ]
