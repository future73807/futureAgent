# futureAgent

面向团队协作的 AI 工作空间，把对话、项目任务、执行计划、交付文件与审计记录放在同一个有权限边界的工作区中。

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

1. **用户端**：注册/登录、多工作区、项目看板、任务管理、对话聊天、文件上传下载、工作模式（计划-审批-执行-复核）
2. **管理员后台**：用户管理、工作区管理、模型中心、技能管理、MCP 服务、权限策略、审计日志
3. **汇报智能体**：汇总已授权数据，生成日报/周报/总结，风险预警，知识库管理，支持 API/Webhook/文件接入
4. **执行治理**：任务计划审批、步骤跟踪、AI 执行（流式输出、超时控制、幂等保护、审计记录）

## 4. 汇报智能体

面向已授权数据接入的汇报智能体，支持日报、总结、风险预警：

1. **数据源接入**：OA、小程序、生产日报、企业机器人、自有 API 等
2. **知识库**：上传文件（PDF/Word/Excel/CSV/TXT/MD）或手动创建文档
3. **预警规则**：生产异常、订单风险、设备故障、交期风险、审批超时
4. **报告生成**：日报、周报、总结报告，按工作区隔离

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

## 6. 验证命令

```powershell
python -m unittest discover -s tests -v
cd frontend && npm run build
cd ../admin-frontend && npm run build
docker compose config --quiet
```

## 7. 安全约定

1. 受保护请求需携带 `Authorization: Bearer <token>` 和 `X-Workspace-ID: <id>`
2. 角色来自签名令牌与数据库成员关系
3. 生产环境必须替换默认凭据、配置 HTTPS、限制 CORS

## 8. 上线前必须完成

1. 配置真实模型供应商并在"模型中心"验证
2. 使用 PostgreSQL + S3 对象存储
3. 配置恶意文件扫描、备份、TLS、限流
4. 替换所有默认凭据和密钥

## 许可证

MIT
