"""轻量 LLM 应答层：对话摘要与知识库检索片段的提示词拼装。

设计边界：
- 模型调用是可以失败的一步：未配置/不可达/超时/空回复一律返回 ``None``，
  由调用方走确定性降级 —— 产品可用性永远不依赖外部供应商。
- 检索片段以带编号的引用块注入，并要求模型不得编造未覆盖的内容。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.model_hub import ModelHub

logger = logging.getLogger(__name__)

DEFAULT_ANSWER_TIMEOUT_SECONDS = 60.0

SYSTEM_PROMPT = (
    "你是团队工作区里的助理。回答必须严格依据用户提供的内容；"
    "资料不足以回答时明确说明缺少什么，禁止编造数字或结论。用简体中文回答。"
)

# 检索片段的来源标签；新增召回来源时在这里登记，避免 prompt 中出现英文枚举值。
_SOURCE_LABELS = {
    "knowledge_base": "知识库",
    "attachment": "附件",
}


def extract_answer_text(response: Any) -> str | None:
    """兼容 LiteLLM 与 langchain 回包两种结构。"""
    try:
        text = response["choices"][0]["message"]["content"]
        if isinstance(text, str) and text.strip():
            return text
    except (TypeError, KeyError, IndexError):
        pass
    try:
        text = response.choices[0].message.content
        if isinstance(text, str) and text.strip():
            return text
    except (AttributeError, IndexError, TypeError):
        pass
    return None


async def generate_answer(
    model_id: str,
    user_prompt: str,
    timeout_seconds: float = DEFAULT_ANSWER_TIMEOUT_SECONDS,
) -> str | None:
    """带预检与超时保护的模型调用；任何失败都返回 None 而不抛出。"""
    readiness_error = ModelHub.readiness_error(model_id)
    if readiness_error:
        return None
    try:
        response = await asyncio.wait_for(
            ModelHub().generate(
                model_id=model_id,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                stream=False,
            ),
            timeout=timeout_seconds,
        )
    except Exception:  # noqa: BLE001 - 供应商异常一律走确定性降级
        logger.warning("assistant_ai: 模型 %s 调用失败，降级为确定性回复", model_id, exc_info=True)
        return None
    return extract_answer_text(response)


def generate_answer_sync(
    model_id: str,
    user_prompt: str,
    timeout_seconds: float = DEFAULT_ANSWER_TIMEOUT_SECONDS,
) -> str | None:
    """同步路由使用的包装：端点在线程池中执行，此处没有运行中的事件循环。"""
    try:
        return asyncio.run(generate_answer(model_id, user_prompt, timeout_seconds))
    except Exception:  # noqa: BLE001
        logger.warning("assistant_ai: 同步模型调用失败，降级为确定性回复", exc_info=True)
        return None


def render_knowledge_context(retrieved: list[dict[str, Any]]) -> str:
    """把工作区知识检索的片段渲染成带编号引用的提示词块。

    没有命中时返回空串：调用方据此完全跳过注入，未建知识库的工作区
    提示词与历史行为逐字一致。
    """
    if not retrieved:
        return ""
    lines = [
        "【工作区知识库检索结果】",
        "以下内容由工作区已登记的资料召回，可能不完整，也可能与问题无关。",
    ]
    for index, item in enumerate(retrieved, start=1):
        source_label = _SOURCE_LABELS.get(item.get("source", ""), "资料")
        lines.append(
            f"[{index}]（{source_label}）{item.get('title', '')} — {item.get('snippet', '')}"
        )
    lines.append("引用资料时在句末标注编号，例如 [1]；资料未覆盖的内容不要编造。")
    return "\n".join(lines)
