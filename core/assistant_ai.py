"""经营/汇报智能体的 LLM 应答层。

设计边界：
- 只回答"用户工作区内已授权数据"的问题，prompt 中显式注入确定性摘要与
  检索片段，并要求模型不得编造。
- 模型未配置/不可达/超时/空回复时返回 ``None``，由调用方降级为原有
  确定性回复 —— 智能体的可用性永远不依赖外部供应商。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.model_hub import ModelHub

logger = logging.getLogger(__name__)

DEFAULT_ANSWER_TIMEOUT_SECONDS = 60.0

SYSTEM_PROMPT = (
    "你是团队的经营与汇报助手。你只能依据下方提供的"
    "【确定性数据摘要】与【检索资料片段】回答问题；"
    "资料不足以回答时必须明确说明缺少哪些数据，禁止编造数字或结论。"
    "引用资料片段时在句子末尾标注其编号，例如 [1]。用简体中文回答。"
)


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


def render_user_prompt(
    question: str,
    deterministic_summary: str,
    retrieved: list[dict[str, Any]],
) -> str:
    """把确定性摘要与召回片段拼装成带编号引用的用户 prompt。"""
    blocks = [f"用户问题：{question}", "", "【确定性数据摘要】", deterministic_summary or "（暂无）", ""]
    blocks.append("【检索资料片段】")
    if retrieved:
        for index, item in enumerate(retrieved, start=1):
            source_label = {
                "knowledge_base": "知识库",
                "business_record": "业务记录",
                "report_record": "汇报记录",
                "attachment": "附件",
            }.get(item.get("source", ""), "资料")
            blocks.append(f"[{index}]（{source_label}）{item.get('title', '')} — {item.get('snippet', '')}")
    else:
        blocks.append("（没有命中的资料片段）")
    blocks.append("")
    blocks.append("请基于以上内容回答用户问题。")
    return "\n".join(blocks)
