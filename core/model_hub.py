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

    @staticmethod
    async def generate(
        model_id: str,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        stream: bool = False,
    ):
        """LiteLLM 统一调用接口"""
        if not LITELLM_AVAILABLE:
            raise ImportError("LiteLLM not installed. Run: pip install litellm")
        response = await acompletion(
            model=model_id,
            messages=messages,
            tools=tools,
            temperature=temperature,
            stream=stream,
        )
        return response

    @staticmethod
    def get_chat_model(
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
        if LITELLM_AVAILABLE:
            from langchain_community.chat_models import ChatLiteLLM
            return ChatLiteLLM(
                model=model,
                temperature=temperature,
                streaming=streaming,
                **kwargs,
            )
        else:
            # 后备方案: 使用 langchain-openai
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                streaming=streaming,
                api_key=settings.openai_api_key,
                **kwargs,
            )

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
