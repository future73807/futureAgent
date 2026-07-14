"""
FastAPI 路由层
提供 REST API 接口
"""
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.responses import Response

from core.agent_engine import AgentEngine
from core.model_hub import ModelHub
from core.skill_manager import SkillManager
from core.mcp_manager import MCPManager
from auth.auth_manager import AuthManager
from config import settings

router = APIRouter()


# ===== 请求模型 =====
class ChatRequest(BaseModel):
    query: str
    user_role: str = "user"
    config: dict = {}


class ChatCompletionRequest(BaseModel):
    query: str
    user_role: str = "user"
    model_id: str = ""


class AgentRequest(BaseModel):
    query: str
    user_role: str = "user"
    model_id: str = ""
    skill_name: str = "default"
    mcp_servers: list[str] = []


# ===== 依赖注入 =====
def get_agent_engine() -> AgentEngine:
    return AgentEngine(
        model_hub=ModelHub(),
        mcp_manager=MCPManager(),
        skill_manager=_get_skill_manager(),
        auth_manager=AuthManager(),
    )


def _get_skill_manager() -> SkillManager:
    """初始化 SkillManager 并注册默认 Skill"""
    from core.skill_manager import Skill

    sm = SkillManager()
    # 注册默认 Skill
    sm.register_skill(Skill(
        name="default",
        description="默认助手",
        system_prompt="你是一个有用的助手。",
    ))
    sm.register_skill(Skill(
        name="chatbot",
        description="聊天机器人",
        system_prompt="你是一个友好的聊天助手，可以回答各种问题。",
    ))
    sm.register_skill(Skill(
        name="data_analyst",
        description="数据分析师",
        system_prompt="你是一个专业的数据分析师，擅长使用 Python 进行数据分析和可视化。",
        allowed_tool_names=["run_python", "read_csv", "write_file"],
    ))
    sm.register_skill(Skill(
        name="coder",
        description="代码助手",
        system_prompt="你是一个专业的编程助手，擅长编写和调试代码。",
        allowed_tool_names=["run_python", "read_file", "write_file"],
    ))
    return sm


# ===== 路由 =====
@router.get("/v1/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "futureAgent"}


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    简单聊天补全 (无 Agent, 直接调用模型)
    """
    engine = get_agent_engine()
    model_id = request.model_id or settings.default_model

    # 权限校验
    engine.auth_manager.check_permission(
        request.user_role, f"model:{model_id}", "use"
    )

    async def stream():
        from litellm import acompletion
        response = await acompletion(
            model=model_id,
            messages=[{"role": "user", "content": request.query}],
            stream=True,
        )
        async for chunk in response:
            yield dict(data=chunk.choices[0].delta.content or "")

    return EventSourceResponse(stream())


@router.post("/v1/chat/agent")
async def agent_chat(request: AgentRequest):
    """
    Agent 模式聊天 (带工具调用)
    """
    engine = get_agent_engine()
    model_id = request.model_id or settings.default_model

    config = {
        "model_id": model_id,
        "skill_name": request.skill_name,
        "mcp_servers": request.mcp_servers,
    }

    async def stream():
        async for chunk in engine.run(
            user_role=request.user_role,
            query=request.query,
            config=config,
        ):
            yield dict(data=chunk)

    return EventSourceResponse(stream())


@router.get("/v1/models")
async def list_models():
    """列出可用模型"""
    return {"models": ModelHub.list_supported_models()}


@router.get("/v1/skills")
async def list_skills():
    """列出可用 Skill"""
    sm = _get_skill_manager()
    return {"skills": [s.model_dump() for s in sm.list_skills()]}


@router.get("/v1/auth/policies")
async def list_policies():
    """列出权限策略"""
    auth = AuthManager()
    return {"policies": auth.get_policies()}
