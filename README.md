基于现有的优秀开源轮子，我为你设计了一个名为 **ModuAgent** 的可扩展 Agent 项目方案。该方案采用模块化设计，完美契合“模型切换、Skill装配、MCP工具接入、权限管理”的需求。
### 一、 技术栈选型
| 模块 | 开源轮子选型 | 选型理由 |
| :--- | :--- | :--- |
| **底层框架** | **FastAPI** | 异步高性能，自带 OpenAPI 文档，适合做 Agent 服务端 |
| **Agent 编排** | **LangGraph** | 支持状态机流转，适合构建带记忆和工具循环的 Agent |
| **模型切换层** | **LiteLLM** | 统一 API 代理，支持 100+ 大模型（OpenAI, Claude, 本地 Ollama 等）无缝切换 |
| **工具协议** | **MCP (Model Context Protocol)** | Anthropic 提出的标准协议，使用 `mcp` 官方 Python SDK |
| **Skill 框架** | **LangChain Tools / 自定义基类** | 将 Skill 封装为标准 Tool，支持动态加载 |
| **权限管理** | **Casbin** | 轻量级、支持 RBAC/ABAC，非常适合细粒度接口和资源权限控制 |
| **持久化** | **PostgreSQL + Redis** | 存储用户配置、会话状态、Casbin 策略；Redis 做缓存 |
---
### 二、 核心架构设计
项目采用分层架构，请求自上而下流转：
```text
┌───────────────────────────────────────────────────────────┐
│                      API Gateway (FastAPI)                 │
├───────────────────────────────────────────────────────────┤
│  Auth & Permission Layer (Casbin)                         │
│  - 验证用户身份                                           │
│  - 校验是否有权使用某 Model / Skill / MCP Tool            │
├───────────────────────────────────────────────────────────┤
│  Agent Orchestrator (LangGraph)                           │
│  - 管理对话状态                                           │
│  - 维护执行图         │
├─────────────┬─────────────┬───────────────────────────────┤
│  Model Hub  │  Skill Hub  │  Tool Hub                     │
│ (LiteLLM)   │ (Prompt/    │ (MCP Client & Local Tools)    │
│             │  Sub-agent) │                               │
├─────────────┴─────────────┴───────────────────────────────┤
│  Infrastructure (PostgreSQL / Redis / Vector DB)          │
└───────────────────────────────────────────────────────────┘
```
---
### 三、 核心模块实现细节与代码设计
#### 1. 模型切换
利用 **LiteLLM**，我们只需维护一个模型配置表，通过传入不同的 `model_name` 即可实现切换。
```python
from litellm import acompletion
from typing import Optional
class ModelHub:
    @staticmethod
    async def generate(model_id: str, messages: list, tools: Optional[list] = None):
        # LiteLLM 统一了不同模型的调用方式
        # model_id 例如: "gpt-4o", "claude-3-5-sonnet", "ollama/llama3"
        response = await acompletion(
            model=model_id,
            messages=messages,
            tools=tools,
            temperature=0.7
        )
        return response
```
#### 2. MCP 工具安装与集成
MCP 工具通常作为独立进程或服务运行。我们设计一个 `MCPManager` 来动态连接和加载 MCP 工具。
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
class MCPManager:
    def __init__(self):
        self.sessions = {} # 存储已连接的 MCP server sessions
    async def install_mcp_server(self, server_name: str, command: str, args: list):
        """动态安装并连接一个 MCP Server"""
        server_params = StdioServerParameters(command=command, args=args)
        
        # 创建连接
        read, write = await stdio_client(server_params).__aenter__()
        session = await ClientSession(read, write).__aenter__()
        self.sessions[server_name] = session
        
        # 初始化
        await session.initialize()
        return f"MCP Server {server_name} installed."
    async def get_mcp_tools(self, server_name: str):
        """获取指定 MCP Server 提供的工具，转换为 LangChain Tool 格式"""
        session = self.sessions.get(server_name)
        if not session:
            return []
        # 使用 langchain-mcp-adapters 将 MCP 工具转为 Agent 可用的 Tool
        return await load_mcp_tools(session)
```
#### 3. Skill 装配
Skill 可以理解为**特定领域的提示词模板 + 专属工具集 + 专属子图**。我们将其抽象为标准配置。
```python
from pydantic import BaseModel
from typing import List, Optional
class Skill(BaseModel):
    name: str
    description: str
    system_prompt: str           # Skill 专属人设和提示词
    allowed_tool_names: List[str] # 该 Skill 允许调用的工具白名单
class SkillManager:
    def __init__(self):
        self.skills_db = {} # 实际可存放在数据库
    def register_skill(self, skill: Skill):
        self.skills_db[skill.name] = skill
    def assemble_skill(self, skill_name: str, available_tools: list) -> dict:
        """装配 Skill，过滤出可用的工具"""
        skill = self.skills_db[skill_name]
        # 根据 Skill 配置，白名单过滤工具
        active_tools = [
            tool for tool in available_tools 
            if tool.name in skill.allowed_tool_names
        ]
        return {
            "system_prompt": skill.system_prompt,
            "tools": active_tools
        }
```
#### 4. 权限管理
使用 **Casbin** 进行 RBAC 权限控制。定义策略：`sub, obj, act` (主体, 资源, 操作)。
**Casbin Model (rbac_model.conf):**
```ini
[request_definition]
r = sub, obj, act
[policy_definition]
p = sub, obj, act
[role_definition]
g = _, _
[policy_effect]
e = some(where (p.eft == allow))
[matchers]
m = g(r.sub, p.sub) && keyMatch2(r.obj, p.obj) && r.act == p.act
```
**权限校验中间件:**
```python
from fastapi import HTTPException
import casbin
class AuthManager:
    def __init__(self, model_path, policy_path):
        self.enforcer = casbin.Enforcer(model_path, policy_path)
    
    def check_permission(self, user_role: str, resource: str, action: str):
        # resource 例如: "model:gpt-4o", "skill:coder", "mcp:filesystem"
        if not self.enforcer.enforce(user_role, resource, action):
            raise HTTPException(status_code=403, detail=f"Permission denied for {resource}")
# 权限策略示例：
# p, admin, *, *               (admin可以操作一切)
# p, developer, model:*, use   (developer可以用所有模型)
# p, user, model:gpt-3.5, use  (user只能用gpt-3.5)
# p, user, skill:chatbot, use  (user只能装配chatbot skill)
```
#### 5. LangGraph 整合引擎
最后，使用 **LangGraph** 将上述组件串联起来。
```python
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage
class AgentEngine:
    def __init__(self, model_hub, mcp_manager, skill_manager, auth_manager):
        self.model_hub = model_hub
        self.mcp_manager = mcp_manager
        self.skill_manager = skill_manager
        self.auth_manager = auth_manager
    async def run(self, user_role: str, query: str, config: dict):
        # 1. 权限校验
        self.auth_manager.check_permission(user_role, f"model:{config['model_id']}", "use")
        self.auth_manager.check_permission(user_role, f"skill:{config['skill_name']}", "use")
        
        # 2. 获取所有可用工具 (本地工具 + MCP工具)
        all_tools = []
        for mcp_server in config.get("mcp_servers", []):
            self.auth_manager.check_permission(user_role, f"mcp:{mcp_server}", "use")
            all_tools.extend(await self.mcp_manager.get_mcp_tools(mcp_server))
            
        # 3. 装配 Skill (过滤工具 + 获取提示词)
        skill_data = self.skill_manager.assemble_skill(config['skill_name'], all_tools)
        
        # 4. 构建消息
        messages = [
            SystemMessage(content=skill_data["system_prompt"]),
            HumanMessage(content=query)
        ]
        
        # 5. 动态创建 LangGraph ReAct Agent 并执行
        # 这里通过 LiteLLM 包装器接入 LangChain
        from langchain_community.chat_models import ChatLiteLLM
        llm = ChatLiteLLM(model=config['model_id'])
        
        agent = create_react_agent(llm, tools=skill_data["tools"])
        
        # 6. 执行并返回流式结果
        async for event in agent.astream_events({"messages": messages}, version="v1"):
            if event["event"] == "on_chat_model_stream":
                yield event["data"]["chunk"].content
```
---
### 四、 数据流与接口设计示例
假设我们提供一个 REST API `/v1/chat/completions`，用户发起请求的流程如下：
1. **请求传入：**
   ```json
   {
     "query": "帮我分析一下桌面的 sales.csv 文件",
     "config": {
       "model_id": "claude-3-5-sonnet",
       "skill_name": "data_analyst",
       "mcp_servers": ["filesystem_server", "python_executor"]
     }
   }
   ```
2. **FastAPI 路由处理：**
   - 解析 Token 获取 `user_role` (如 "developer")。
   - 调用 `AgentEngine.run()`。
3. **引擎内部流转：**
   - **AuthManager** 校验 "developer" 是否能用 claude-3.5、data_analyst skill 和 filesystem MCP。
   - **MCPManager** 连接文件系统 MCP 和 Python 执行 MCP，拿到 `read_csv`, `run_python` 工具。
   - **SkillManager** 装配 data_analyst，设定系统提示词为“你是一个数据分析师...”，并保留 `read_csv` 和 `run_python` 工具。
   - **LangGraph Agent** 启动，通过 LiteLLM 调用 Claude，发现需要读文件，调用 MCP 的 `read_csv` 工具，再调用 `run_python` 分析数据，最终生成回答。
4. **流式返回：** 将结果通过 SSE (Server-Sent Events) 推送给前端。
### 五、 项目目录结构建议
```text
modu_agent/
├── api/                  # FastAPI 路由层
│   ├── routes.py
│   └── deps.py
├── core/                 # 核心引擎
│   ├── agent_engine.py   # LangGraph 编排
│   ├── model_hub.py      # LiteLLM 模型管理
│   ├── skill_manager.py  # Skill 装配器
│   └── mcp_manager.py    # MCP 客户端管理
├── auth/                 # 权限模块
│   ├── casbin_model.conf
│   └── auth_manager.py
├── db/                   # 数据库模型与操作
├── skills/               # 具体的 Skill 定义 (YAML或JSON)
│   ├── coder.yaml
│   └── data_analyst.yaml
├── config.py             # 全局配置
└── main.py               # 启动入口
```
### 六、 总结与优势
1. **解耦性强**：模型使用 LiteLLM，工具使用 MCP，权限使用 Casbin，任何一层都可以独立替换。
2. **未来扩展性**：MCP 协议天然支持丰富的生态（如 GitHub, Postgres, Slack 等 MCP Server），无需自己写各种 API 对接代码。
3. **企业级可用**：Casbin 提供了企业级的权限控制，确保不同部门/级别的用户只能使用被授权的模型和工具。
4. **开发效率高**：LangGraph 的 `create_react_agent` 极大地简化了 Agent 的工具调用循环逻辑，开箱即用。
