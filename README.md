# futureAgent 模块化 AI Agent 框架

基于开源轮子拼装的模块化 AI Agent 框架，所有组件都使用现成的高质量开源项目。

## 🏗️ 架构设计

```
┌───────────────────────────────────────────────────────────┐
│                      API Gateway (FastAPI)                 │
├───────────────────────────────────────────────────────────┤
│  Auth & Permission Layer (Casbin)                         │
│  - 验证用户身份                                           │
│  - 校验是否有权使用某 Model / Skill / MCP Tool            │
├───────────────────────────────────────────────────────────┤
│  Agent Orchestrator (LangGraph)                           │
│  - 管理对话状态                                           │
│  - 维护执行图                                             │
├─────────────┬─────────────┬───────────────────────────────┤
│  Model Hub  │  Skill Hub  │  Tool Hub                     │
│ (LiteLLM)   │ (Prompt/    │ (MCP Client & Local Tools)    │
│             │  Sub-agent) │                               │
├─────────────┴─────────────┴───────────────────────────────┤
│  Infrastructure (PostgreSQL / Redis / Vector DB)          │
└───────────────────────────────────────────────────────────┘
```

## 🔧 技术栈

| 模块 | 开源轮子 | GitHub |
|------|---------|--------|
| **Web 框架** | FastAPI | https://github.com/fastapi/fastapi |
| **Agent 编排** | LangGraph | https://github.com/langchain-ai/langgraph |
| **模型切换** | LiteLLM | https://github.com/BerriAI/litellm |
| **工具协议** | MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk |
| **权限管理** | PyCasbin | https://github.com/casbin/pycasbin |
| **ORM** | SQLModel | https://github.com/fastapi/sqlmodel |
| **可观测性** | Langfuse | https://github.com/langfuse/langfuse |
| **数据库** | PostgreSQL + pgvector | https://github.com/pgvector/pgvector |
| **反向代理** | Nginx | https://github.com/nginx/nginx |
| **前端** | @ant-design/x + React | https://github.com/ant-design/x |

## 📁 项目结构

```
futureAgent/
├── api/                    # FastAPI 路由层
│   ├── __init__.py
│   └── routes.py           # REST API 接口
├── auth/                   # 权限模块 (Casbin)
│   ├── __init__.py
│   ├── auth_manager.py     # 权限管理器
│   ├── rbac_model.conf     # Casbin 模型配置
│   └── rbac_policy.csv     # 权限策略
├── core/                   # 核心引擎
│   ├── __init__.py
│   ├── agent_engine.py     # LangGraph 编排引擎
│   ├── model_hub.py        # LiteLLM 模型管理
│   ├── skill_manager.py    # Skill 装配器
│   └── mcp_manager.py      # MCP 客户端管理
├── db/                     # 数据库模块
├── nginx/                  # Nginx 配置
│   └── nginx.conf
├── frontend/               # 前端 (React + @ant-design/x)
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── skills/                 # Skill 定义 (YAML)
│   ├── chatbot.yaml
│   ├── data_analyst.yaml
│   └── coder.yaml
├── config.py               # 全局配置
├── main.py                 # 启动入口
├── requirements.txt        # Python 依赖
├── docker-compose.yml      # Docker Compose
├── Dockerfile             # Docker 构建
├── .env.example           # 环境变量模板
└── .gitignore
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <your-repo-url>
cd futureAgent

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装 Python 依赖
pip install -r requirements.txt

# 安装前端依赖
cd frontend
npm install
cd ..
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 3. 启动服务

```bash
# 方式一: 本地启动 (推荐开发用)

# 终端 1: 启动后端
python main.py

# 终端 2: 启动前端
cd frontend
npm run dev

# 方式二: 使用 Docker Compose (推荐生产部署)
docker-compose up -d
```

### 4. 访问地址

| 服务 | 地址 | 说明 |
|------|------|------|
| **前端 Dashboard** | http://localhost:5173 | React + @ant-design/x |
| **futureAgent API** | http://localhost:8000 | FastAPI 主服务 |
| **API 文档 (Swagger)** | http://localhost:8000/docs | 交互式 API 文档 |
| **API 文档 (ReDoc)** | http://localhost:8000/redoc | 另一种文档格式 |
| **Nginx 代理** | http://localhost | 反向代理入口 |
| **MCP Server** | http://localhost:8050 | MCP 工具服务 |
| **PostgreSQL** | localhost:5432 | 数据库 |

### 5. 默认账号密码

| 服务 | 账号 | 密码 | 说明 |
|------|------|------|------|
| **PostgreSQL** | `postgres` | `password` | 数据库超级用户 |
| **权限角色** | `admin` | - | 管理员，拥有所有权限 |
| **权限角色** | `developer` | - | 开发者，可用所有模型/工具 |
| **权限角色** | `user` | - | 普通用户，仅限 gpt-3.5-turbo + chatbot |

> ⚠️ 账号密码配置在 `docker-compose.yml` (数据库) 和 `auth/rbac_policy.csv` (权限策略) 中，生产环境请务必修改！

## 📡 API 使用示例

### 简单聊天

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "query": "你好，介绍一下你自己",
    "user_role": "developer",
    "model_id": "gpt-4o-mini"
  }'
```

### Agent 模式 (带工具调用)

```bash
curl -X POST http://localhost:8000/api/v1/chat/agent \
  -H "Content-Type: application/json" \
  -d '{
    "query": "帮我分析一下桌面的 sales.csv 文件",
    "user_role": "developer",
    "model_id": "claude-3-5-sonnet",
    "skill_name": "data_analyst",
    "mcp_servers": ["filesystem_server", "python_executor"]
  }'
```

### 列出可用模型

```bash
curl http://localhost:8000/api/v1/models
```

### 列出可用 Skill

```bash
curl http://localhost:8000/api/v1/skills
```

## 🔐 权限管理

权限策略定义在 `auth/rbac_policy.csv` 中：

```csv
# admin 可以操作一切
p, admin, *, *

# developer 可以用所有模型
p, developer, model:*, use

# user 只能用 gpt-3.5
p, user, model:gpt-3.5-turbo, use

# 角色继承：admin 继承 developer
g, admin, developer
```

## 🧩 添加自定义 Skill

在 `skills/` 目录下创建 YAML 文件：

```yaml
name: my_custom_skill
description: 我的自定义 Skill
system_prompt: |
  你是一个专业的XXX助手，擅长...
allowed_tool_names:
  - tool_name_1
  - tool_name_2
```

然后在 `api/routes.py` 中注册：

```python
sm.register_skill(Skill(
    name="my_custom_skill",
    description="我的自定义 Skill",
    system_prompt="...",
    allowed_tool_names=["tool_name_1", "tool_name_2"],
))
```

## 🔄 模型切换

通过 LiteLLM 支持 100+ 模型无缝切换：

| 模型 ID | 提供商 |
|---------|--------|
| `gpt-4o` | OpenAI |
| `gpt-4o-mini` | OpenAI |
| `claude-3-5-sonnet-20241022` | Anthropic |
| `ollama/llama3` | Ollama (本地) |
| `gemini/gemini-1.5-pro` | Google |

## 📊 数据流

```
用户请求 → FastAPI 路由
         → Casbin 权限校验
         → LiteLLM 选择模型
         → SkillManager 装配 Skill
         → MCPManager 加载工具
         → LangGraph Agent 执行
         → SSE 流式返回
```

## 📝 开源轮子来源

1. **FastAPI MCP LangGraph Template** - https://github.com/NicholasGoh/fastapi-mcp-langgraph-template
   - 提供了 FastAPI + LangGraph + MCP + Langfuse + PostgreSQL 的基础模板
   
2. **LiteLLM** - https://github.com/BerriAI/litellm
   - 统一 API 代理，支持 100+ 大模型无缝切换
   
3. **PyCasbin** - https://github.com/casbin/pycasbin
   - 轻量级权限管理，支持 RBAC/ABAC

## 📄 License

MIT License
