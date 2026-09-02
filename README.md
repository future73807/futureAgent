# futureAgent

面向团队协作的 AI 工作空间，把对话、项目任务、执行计划、交付文件、定时自动化与审计记录放在同一个有权限边界的工作区中。

## 1. 产品组成

| 服务 | 技术 | 端口 |
| --- | --- | --- |
| 用户端 | React + Ant Design X | `8081` |
| 管理员后台 | React + Ant Design | `8082` |
| API 服务 | FastAPI + LiteLLM | `8000` |
| PostgreSQL | 数据库 | `25432` |
| MCP 服务 | 工具服务 | `8050` |

## 2. 本地访问

| 项目 | 地址 |
| --- | --- |
| 用户端 | `http://localhost:8081/` |
| 管理员后台 | `http://localhost:8082/` |
| API | `http://127.0.0.1:8000` |
| 接口目录 | `http://127.0.0.1:8000/docs` |
| 默认管理员 | `admin@futureagent.dev` / `ChangeMe123!` |

> Windows 若 `127.0.0.1` 访问异常，改用 IPv6 回环：`http://[::1]:8000`

## 3. 已实现功能

1. **用户端**：注册/登录、多工作区、项目看板（拖拽换列 + 截止日日历 + 任务评论）、任务管理、对话聊天（分页加载 + 滚动摘要记忆）、全局搜索、深浅色主题、文件上传下载、工作模式（计划-审批-执行-复核）
2. **管理员后台**：用户管理（创建账号/重置密码）、工作区管理（创建/级联删除）、模型中心、技能管理、MCP 服务、权限策略、审计轨迹（条件筛选）
3. **汇报智能体**：汇总已授权数据生成日报/周报/总结，风险预警，知识库检索（RAG），自动化任务调度，支持 API/Webhook/文件接入
4. **经营智能体**：三类隔离助手（老板/私事/公务），已授权数据问答接入真实模型（未配置时降级为确定性摘要）
5. **交付物中心**：AI 可直接产出 xlsx/docx/图表 PNG；工作区文件一键登记为可下载交付物
6. **通知中心**：任务指派、计划批准、AI 执行结果、预警扫描的站内通知；Webhook/企业微信/飞书/钉钉出口推送
7. **自动化**：cron 定时生成日报/周报、扫描预警，支持立即执行与启停管理
8. **执行治理**：任务计划审批、步骤跟踪、AI 执行（流式输出、超时控制、幂等保护、审计记录）；PostgreSQL 部署下同一任务共享 LangGraph 会话记忆

## 4. 汇报智能体

面向已授权数据接入的汇报智能体，支持日报、周报、风险预警：

1. **数据源接入**：OA、小程序、生产日报、企业机器人、自有 API 等
2. **知识库**：上传文本类文件或手动创建；问答时按关键词检索引用（升级 pgvector 即为向量召回）
3. **预警规则**：生产异常、订单风险、设备故障、交期风险、审批超时；可定时扫描并推送
4. **报告生成**：日报、周报按工作区隔离，支持手动与 cron 定时生成

## 5. 快速启动

```powershell
# Docker Compose（推荐）
docker compose up -d --build

# 本机运行
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000

cd frontend && npm install && npm run dev
cd ../admin-frontend && npm install && npm run dev
```

## 6. 模型与 API 配置

先从示例生成只在本机使用的配置文件；`.env` 已被 Git 忽略，不要把真实密钥提交到仓库：

```powershell
Copy-Item .env.example .env
```

至少配置一种可用的模型路由：

| 路由 | `.env` 变量 | 说明 |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY`、可选 `OPENAI_BASE_URL` | 默认使用 OpenAI 官方兼容地址 |
| Anthropic | `ANTHROPIC_API_KEY` | Claude 模型直连 |
| Google | `GOOGLE_API_KEY` | Gemini 模型直连 |
| LongCat | `LONGCAT_API_KEY`、可选 `LONGCAT_API_BASE` | OpenAI 兼容接口 |
| Ollama | `OLLAMA_BASE_URL` | Compose 默认连接 `host.docker.internal:11434`；API 在宿主机直接运行时使用 `http://localhost:11434` |
| LiteLLM 代理 | `LITELLM_PROXY_URL`、`LITELLM_MASTER_KEY` | URL 非空时，支持的模型统一经内部代理路由 |

修改后重新启动 API，并在管理员后台的“模型中心”逐个执行真实探针。配置项只代表存在路由；只有探针成功才代表供应商、凭据、网络和模型名称全部可用。

生产环境还必须填写独立的 `JWT_SECRET_KEY`、`MCP_WORKSPACE_SIGNING_KEY` 和管理员密码，并使用 HTTPS。

### 行为配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MAX_CONCURRENT_AGENT_RUNS_PER_WORKSPACE` | `2` | 每工作区同时进行的 AI 执行数 |
| `AGENT_RUN_TIMEOUT_SECONDS` | `180` | 单次 AI 执行的最长时长 |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `60` | 每 IP 每分钟认证尝试上限（0 关闭；多副本部署建议在网关层限制） |
| `RUN_MIGRATIONS_ON_STARTUP` | `false` | 生产启动时自动执行数据库迁移 |

## 7. 验证命令

```powershell
python -m unittest discover -s tests -v
cd frontend && npm run build
cd ../admin-frontend && npm run build
docker compose config --quiet
```

## 8. 安全约定

1. 受保护请求需携带 `Authorization: Bearer <token>` 和 `X-Workspace-ID: <id>`
2. 角色来自签名令牌与数据库成员关系
3. 生产环境必须替换默认凭据、配置 HTTPS、限制 CORS
4. 内置 MCP 文件工具只接受 API 通过 `MCP_WORKSPACE_SIGNING_KEY` 签发的工作区声明，并在 MCP 服务端强制映射到独立目录；生产环境必须替换该密钥且不得把它发给浏览器
5. `run_python` 不进入共享多租户 Agent；只有独占 MCP 容器可显式设置 `MCP_ENABLE_PYTHON_TOOL=true`
6. 登录/注册/刷新接口内置滑动窗口限流；docx/xlsx 等办公文档解析使用 defusedxml 并拒绝 DOCTYPE/ENTITY 声明
7. 智能体问答只使用本工作区已授权数据：prompt 注入确定性摘要与检索片段，模型不可用时降级为规则摘要，绝不调用未授权外部系统

## 9. 上线前必须完成

1. 配置真实模型供应商并在"模型中心"验证
2. 使用 PostgreSQL + S3 对象存储（PostgreSQL 部署同时启用 LangGraph 会话记忆与 pgvector 检索升级路径）
3. 配置恶意文件扫描、备份、TLS；多副本部署时在网关配置认证限流
4. 替换所有默认凭据和密钥

## 10. 功能路线图

对标分析见 `docs/workbuddy-gap-analysis.md`。已完成的 P0/P1 能力：智能体 LLM 化与知识检索、定时自动化、交付物中心、通知中心、消息分页与全局搜索、PDF 解析、看板拖拽/日历/评论、暗色模式、PWA 清单、管理端运营闭环、认证限流。后续候选：pgvector 向量召回、多 Agent 并行编排、IM 入站指令闭环。

## 许可证

MIT
