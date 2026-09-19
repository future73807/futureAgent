# futureAgent

面向团队协作的 AI 工作空间，把对话、知识库、项目任务、执行计划、交付文件与审计记录放在同一个有权限边界的工作区中。

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

1. **用户端**：注册/登录、多工作区、Code 工作台（单形态，无模式切换器）、项目看板（拖拽换列 + 截止日日历 + 任务评论 + 工作项归档/恢复）、任务管理、对话聊天（分页加载 + 滚动摘要记忆）、全局搜索、深浅色主题、文件上传下载、工作模式（计划-审批-执行-复核）
2. **管理员后台**：用户管理（创建账号/重置密码/删除无数据账号）、工作区管理（创建/级联删除）、模型中心、技能管理、MCP 服务、权限策略、审计轨迹（条件筛选）
3. **知识库（RAG）**：工作区文档的知识检索层，智能助手回答时自动召回命中片段并在回复里标注引用编号；面板支持创建/上传/编辑/删除文档，写操作自动重建向量切块
4. **交付物中心**：AI 可直接产出 xlsx/docx/图表 PNG；工作区文件一键登记为可下载交付物
5. **通知中心**：任务指派、计划批准、AI 执行结果的站内通知；Webhook/企业微信/飞书/钉钉出口推送
6. **执行治理**：任务计划审批、步骤跟踪、AI 执行（流式输出、超时控制、幂等保护、审计记录）；PostgreSQL 部署下同一任务共享 LangGraph 会话记忆
7. **运行模式**：chat/plan/agent/goal/loop 五档，对话页与工作模式均可逐次选择，模式随执行记录持久化以便重试复现
8. **权限档位**：工作区级的默认权限/自动审批/完全访问三档，受部署上限约束，调整写入审计
9. **用量统计**：按模型/账号/技能/模式/日期聚合模型真实上报的 token、调用次数与耗时；管理端与用户端各有视图
10. **差异分析**：AI 覆写工作区文件前自动快照，工作模式“变更”页可看版本清单与 unified / 左右对照差异
11. **子代理**：技能可显式开启 `dispatch_subagent`，由父代理派生子代理完成子任务，受深度/并发/共享超时预算约束
12. **插件市场**：插件（MCP 服务）与技能两个页签，支持搜索、分类筛选、精选位与卡片式安装/使用；数据全部来自后端真实注册表，不是前端写死的展示数据
13. **设置面板**：账号 / 用量管理 / 通用 / 权限审批 / MCP / 模型 / 浏览器 / 规则与记忆 / 关于 九个分区；规则与记忆、浏览器开关按工作区落库，规则会拼进每次执行的系统提示
14. **模型档案**：`MODEL_PROFILES_JSON` 可给单个模型指定端点并声明能力（工具调用 / 视觉 / 上下文与输出上限），设置面板据此显示能力标签
15. **创造模式**：用一段人设 + 模型 + 技能 + 工具拼出自建智能体，卡片列表可增删改；「使用」把预设灌进输入卡并带着 `agent_id` 进入对话，人设由服务端注入提示词（排在技能说明之后、工作区规则之前）。智能体**只是可复用的运行预设，不携带任何额外权限**——执行时工具授权仍按发起人身份与工作区授权档位判定。模型 / 工具在创建时即校验，非法值挡在创建这一步而不是运行期才报错
16. **定时任务**：在对话里让智能体把一句提示词安排成周期执行（"每天早上九点帮我……"），到点自动跑一次并产出新对话与通知；创建、查看、停用都在对话里完成，没有单独的管理页（见第 5 章）

### 用户端视觉基线

用户端采用**单一 Code 形态**与中性灰阶视觉：

1. **不做模式切换器。** 侧边栏顶部只放品牌与「新建任务」，没有 Work / Code / Design 之类的分段控件——本产品只有一种工作形态。
2. **不用渐变、不用蓝紫装饰色。** 主操作取近黑（`--primary: #1f1f22`），层级只由底色、1px 描边与留白表达；彩色仅保留给语义状态（成功 / 警告 / 危险）。
3. **不做整块入场动画。** 切页时旧内容一直保留到新页面就绪（见下），内容区不会出现空帧。
4. 视觉令牌集中在 `frontend/src/index.css` 顶部的 `:root` 与 `[data-theme='dark']`，改主题只改这两处。

`frontend/e2e/click-flow.mjs` 里有一条**闪烁探针**：切页期间逐帧采样
`.workspace-content`，只要出现一帧内容为空或整屏加载骨架就判失败——视觉回归
不能只靠肉眼。

### 首屏与切页为什么不会闪
三处历史原因，都已在代码里注明：

1. 路由分包原先用 `React.lazy` + `Suspense`。`React.lazy` 的**首次**渲染一定会
   挂起并提交一次 Suspense 回退，即使分包早已下载到本地，于是"点一下导航闪一下
   骨架"。现在改为自维护的已加载组件表（`loadRoute` / `useRouteComponent`），
   首屏稳定后空闲预取，切页是同步渲染；预取未完成时保留上一页节点。
2. 工作区首屏加载把 MCP 探针（连接超时约 2.8s）与模型探针（真实打供应商约 2s）
   放进同一个 `Promise.all`，接口全慢在等待上。现在慢数据移出阻塞路径，先渲染
   毫秒级返回的成员/项目/任务/会话。
3. `canProbeMcp` 参与 `loadWorkspace` 的依赖，角色从"未知"变为"owner"时会再触发
   一次全量加载（首屏发两遍请求）。现在改为 ref 读取，依赖只剩 `workspaceId`。
4. 应用外壳原先用 `min-height: 100vh`，页面本身会随内容变长；浮层（下拉、菜单）
   是 `position: absolute` 挂在 body 上的，靠近窗口下沿时会把文档撑高，页面因此
   冒出滚动条——滚动条一出现一消失，内容列就横移一下，看上去就是"闪一下"。
   现在外壳锁死为视口高（`.workspace-layout { height: 100dvh; overflow: hidden }`），
   滚动只发生在内容区内部；侧边栏底部的菜单与工作区选择器显式 `placement="top*"`
   向上展开，不再依赖 `rc-trigger` 的自动翻转。
5. 内部滚动容器统一加 `scrollbar-gutter: stable`。Windows 上滚动条占 9px（本项目
   自定义过宽度），`.workspace-content` 原先没有预留槽位，于是"某个页面内容刚好
   变高→冒出滚动条→输入卡与整列横移 9px"，每切一次页就抖一下。
   `frontend/e2e/audit-scrollbar.mjs` 会切遍全部 7 个页面，断言内容区宽度恒定。
   **注意：Playwright headless 默认带 `--hide-scrollbars`（滚动条宽度 0），会完全
   掩盖这类问题；所有 E2E 脚本都显式关掉了该参数（`ignoreDefaultArgs`）。**
6. `@media (prefers-reduced-motion: reduce)` 里**不能**用 `*` 覆盖
   `transition-duration` / `animation-duration`。antd 浮层的定位链路是
   rc-trigger → rc-align → dom-align + rc-motion：先把浮层渲染在视口外
   （实测 `left: -12800px`）再测量对齐，这段位移由 CSS transition/animation 驱动。
   用 `!important` 把 `*` 的时长压成 .01ms，对齐流程走不完，浮层就永远停在视口外
   ——**所有下拉都"点了没反应"，同时那个 -12800px 的绝对定位元素把文档撑到
   13061px 宽，闪出一条横向滚动条**。系统打开"减少动态效果"（Windows 辅助功能）
   就 100% 命中，且无痕模式无效、清缓存无效。现在只关掉自己写的装饰性过渡，
   不碰 antd 的浮层机制；`frontend/e2e/audit-reduced-motion.mjs` 显式模拟该偏好。

### 运行模式

| 模式 | 工具面 | 行为 |
| --- | --- | --- |
| `chat` | 不绑定 | 纯模型对话，不调用任何工具 |
| `plan` | 只读子集 | 调研后仅输出结构化计划 JSON，不改写文件、不生成交付物 |
| `agent` | 已选工具全量 | 规划 + 工具自主循环（缺省模式，与引入模式前行为一致） |
| `goal` | 已选工具全量 | 给定目标与达成标准，监督节点判定未达成则回注指令再迭代 |
| `loop` | 已选工具全量 | 按停止条件反复迭代，每轮基于上一轮结果改进 |

`goal` 必须传 `goal`，`loop` 必须传 `success_criteria`，否则服务端返回 422——缺了判据监督者只能一直返回“未达成”直到烧完轮次预算。监督判定结果无法解析时以 `judge_unavailable` 终止，而不是继续消耗 token。

### 权限档位

| 档位 | 计划审批 | 步骤复核 | 工具广度 |
| --- | --- | --- | --- |
| `default` | 必须人工批准 | 人工 | 按部署开关与 RBAC |
| `auto_approve` | 保存即批准（写审计 `work_plan.auto_approved`） | 人工 | 同 default |
| `full_access` | 自动批准 | 执行成功后直接标完成 | 额外放开工作区写工具 |

档位归工作区所有，仅所有者可改；单次请求只能在工作区档位基础上**向下**收紧，向上取值被静默丢弃。`MAX_PERMISSION_MODE` 可设部署上限（非法取值按最严格的 `default` 处理）。与工作区档位、请求档位三者取最严。

**档位只放宽人工审批环节。** Casbin RBAC、租户目录 HMAC 隔离、以及 `run_python` 永不进入多租户 Agent 这三条在任何档位下都不变。

## 4. 知识库（RAG）

智能体回答时引用的工作区资料都在这里维护，入口是侧边栏「知识库」：

1. **文档维护**：手动创建或上传文本类文件（Markdown / CSV / JSON / YAML / HTML / XML，单文件上限约 400 KB），可编辑标题、说明与正文，删除时会级联清掉它的向量切块；只读成员只能查看。
2. **切块与索引**：每次写入按 800 字符（重叠 100）切块，最多 20 块；启用向量化后一并写入切块向量。
3. **混合检索**：对话时**关键词 + 向量余弦融合**召回（权重 6.0），命中片段以带编号的引用块注入系统提示词，模型被要求标注 `[1]` 这样的来源；未建知识库的工作区完全不注入，与历史行为一致。
4. **向量化配置**：`EMBEDDING_PROVIDER=ollama` + `EMBEDDING_MODEL=qwen3-embedding`（`ollama pull qwen3-embedding`）启用本地 Qwen 向量召回，未配置时自动退回关键词；Postgres 部署自动启用 pgvector 原生向量列与 HNSW 余弦索引（维度由 `EMBEDDING_DIM` 决定）。

## 5. 定时任务（由智能体安排）

定时任务在对话里创建，没有单独的管理页：直接说"每天早上九点，把工作区昨天新增的任务与 AI 执行结果总结成一段简报"，智能体会把**时间**与**提示词**写成一条任务。

- **工具**：`schedule_task`（创建）、`list_scheduled_tasks`（查看）、`cancel_scheduled_task`（默认停用、可要求删除）。工作区与发起人由服务端在工具签名之外绑定，模型既不能把任务塞进别的工区，也不能伪造发起人；只读成员的工具集里不出现这三个工具。它们在对话模式也保留——"每天早上帮我……"本来就是对话里最常被直接说出口的诉求。
- **到点执行**：按 cron 触发，每次执行**新建一个对话**（用户消息=任务提示词，助手消息=模型回答），并推送一条通知指回这个对话；执行时同样会做知识库召回，技能白名单里的工具也照常可用（创建的示例任务就在执行中调用了 `list_scheduled_tasks`）。
- **失败留痕**：原因写进任务状态、这次对话与审计；通知只在"由好变坏"时发一次，上游长时间不可用不会把通知中心刷满。
- **权限**：无人值守的执行固定用最严权限档（不自动批准、不自动完成步骤），并以**发起人当前的工作区角色**运行；发起人一旦离开工作区，任务会带着原因跳过，而不是继续以他的名义执行。
- **时区与模式**：cron 按服务器本地时区解析（容器里通常是 UTC），工具描述里带当前时间，模型据此把"明天早上""工作日下午六点"换算成表达式；任务只能选 chat / agent / plan——goal 与 loop 需要目标或停止条件，无人值守下无法终止，创建时就被拒绝。
- **上限**：单工作区最多 20 条；同名同 cron 的启用任务不会重复创建。

## 6. 快速启动

```powershell
# Docker Compose（推荐）
docker compose up -d --build

# 本机运行
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000

cd frontend && npm install && npm run dev
cd ../admin-frontend && npm install && npm run dev
```

## 7. 本地开发启用 MCP（联网搜索 / 文件工具 / 交付物生成）

本地不开 Docker 也能用 MCP 工具链，三个终端即可：

```powershell
# 终端 1：启动 MCP 工具服务（默认监听 8050，签名密钥默认与 API 一致）
py mcp_server/server.py

# 终端 2：以启用工作区工具的方式启动 API
#   （.env 写入 ENABLE_LOCAL_MCP_TOOLS=true 亦可）
ENABLE_LOCAL_MCP_TOOLS=true python -m uvicorn main:app --port 8000

# 终端 3：前端
cd frontend && npm run dev
```

无需 `.env`：`MCP_SERVERS_JSON` 缺省即指向 `http://localhost:8050/mcp`，
MCP 服务的签名密钥默认与 API 一致。启动后在对话页“按需启用工具”选择
`工作区与联网工具`，即可让 AI 联网搜索、读写工作区文件、生成 xlsx/docx/
图表并登记为交付物。联网搜索无需任何 API 密钥（DuckDuckGo HTML，被软拦截时
自动退到 Bing HTML）。

两处与运行环境有关的开关，排障时先看这里：

```powershell
# 1) 换端口：MCP 服务的端口由环境变量决定，必须与 MCP_SERVERS_JSON 一致
#    （本机 7991-8090 常被 Windows 保留段整段占用 → 8050/8051 绑不上）
$env:MCP_SERVER_PORT=8150; py mcp_server/server.py
$env:PYTHON_TOOLS_MCP_PORT=8151; py mcp_server/project_tools_server.py

# 2) 工作区文件根：API 与 MCP 服务必须指向同一个目录，否则"文件工具找不到文件"
#    （API 读 WORKSPACE_FILES_ROOT，MCP 读 MCP_WORKSPACE_ROOT）
$env:MCP_WORKSPACE_ROOT='D:\Desktop\test'; py mcp_server/server.py

# 3) 走 Clash/TUN 一类 fake-IP 代理时，DNS 会解析成 198.18.0.0/15，
#    联网工具默认按"私有地址"拒绝；确认本机由可信代理接管后显式打开：
$env:MCP_WEB_ALLOW_DNS_FAKE_IPS='true'; py mcp_server/server.py
```

`scripts/seed_python_demo.py` 会把联调用的 python-demo 项目（故意留一条失败用例）
写进上面这个工作区根目录：`py scripts/seed_python_demo.py --workspace <工作区 id>`，
之后可在「规划 → 批准 → 自主执行」闭环里让智能体定位并修复它。

要再接一个**自己的**本地工具服务（例如给某个项目加只读探查与跑测试的工具），
把它加进 `MCP_SERVERS_JSON` 后，还要在 `MCP_WORKSPACE_SCOPED_SERVERS_CSV`
里登记服务名，它才会收到 API 签发的工作区声明、从而拿到该租户的文件根：

```powershell
MCP_SERVERS_JSON={"local_tools":"http://localhost:8050/mcp","python_tools":"http://localhost:8051/mcp"}
MCP_WORKSPACE_SCOPED_SERVERS_CSV=local_tools,python_tools
```

未登记的服务收不到任何租户信息，它的文件类工具会以“缺少有效的工作区授权”
失败关闭——这是刻意的：声明等于租户边界，只发给部署方信任的服务。

## 8. 模型与 API 配置

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

## 9. 验证命令

```powershell
python -m unittest discover -s tests -v
cd frontend && npm run build && npm test
# E2E 冒烟（需先启动 API 与前端）：
#   cd frontend && npm run dev 或 npx vite preview --port 8899
cd frontend && npm run e2e:smoke
# 模拟点击全流程验收（52 项：登录、切页、插件市场安装/使用、设置面板九个
# 分区与偏好落库、建项目/任务、配置 chips、真实模型问答、搜索、主题、退出，
# 并逐帧检测切页闪烁）
cd frontend && npm run e2e
# 交互体检（154 项）：
#   - 创造模式 10：新建 → 卡片出现 → 使用 → 对话页提示条 → 退出 → 删除，
#     并断言"人设为空"会被前端拦下、运行模式下拉里有「创造模式」且点了能跳页。
#   - 减少动效 13：模拟系统开着"减少动态效果"（Windows 辅助功能），断言每个浮层
#     仍落在视口内、且过程中不闪出滚动条。系统级偏好差异必须显式模拟。
#   - 选项可选性 8：每个下拉都真的选中一项并断言界面生效。
#   - 全站下拉 36 / 滚动条与浮层 76 / 窄屏 11。
#   改交互后先跑这个。
cd frontend && npm run e2e:audit
# 运行模式与工具链验收（18 项）：对话 / 规划 / 自主 / 目标 / 循环五档，
# 联网搜索（web_search 工具链）、双 MCP 服务、技能、创造模式，并跑通
# 「规划 → 保存为工作计划 → 批准 → 自主执行 → 真的写入工作区文件」闭环，
# 结束后清理本轮造出的智能体与技能。
#   E2E_MODEL=<模型 id> 指定被测模型（默认 local-mock 替身）
cd frontend && node e2e/modes-capabilities.mjs
# 管理端全页面点击巡检：逐个页面、逐个非破坏性按钮点击并断言有反应，
# 截图落在 admin-frontend/e2e/screens/，结构化结果在 e2e/last-run.json
cd ../admin-frontend && node e2e/sweep.mjs
# 技能复制回归（对应 POST /v1/skills/{name}/copy）
cd ../frontend && node e2e/admin-skill-copy.mjs
# 登录页是否铺满视口（三种宽度）
cd frontend && npm run e2e:login
# 视觉走查截图 → frontend/e2e/screens/
cd frontend && node e2e/screens.mjs
cd ../admin-frontend && npm run build
docker compose config --quiet

# 清理可再生成的产物（构建输出、E2E 截图与失败现场、__pycache__、日志）：
# 先干跑列清单，加 --apply 真删；这些都不在 git 里，随时会由构建/测试重建
py scripts/clean_artifacts.py --apply
```

联调素材（工作区文件目录不入库，用脚本重放）：`py scripts/seed_python_demo.py`
写入 `python-demo` 示例项目（自带一条失败用例），`mcp_server/project_tools_server.py`
是配套的第二个 MCP 服务（项目只读探查 + 跑测试 + 语法检查），技能
`python_demo_guardian` 给出该项目的改动规范。

`E2E_BASE_URL` 可覆盖被测地址（默认 `http://localhost:5173`）。E2E 使用本机
Edge/Chrome（`E2E_CHANNEL` 可换），无需下载浏览器二进制。

## 10. 安全约定

1. 受保护请求需携带 `Authorization: Bearer <token>` 和 `X-Workspace-ID: <id>`
2. 角色来自签名令牌与数据库成员关系
3. 生产环境必须替换默认凭据、配置 HTTPS、限制 CORS
4. 内置 MCP 文件工具只接受 API 通过 `MCP_WORKSPACE_SIGNING_KEY` 签发的工作区声明，并在 MCP 服务端强制映射到独立目录；生产环境必须替换该密钥且不得把它发给浏览器
5. `run_python` 不进入共享多租户 Agent；只有独占 MCP 容器可显式设置 `MCP_ENABLE_PYTHON_TOOL=true`
6. 登录/注册/刷新接口内置滑动窗口限流；docx/xlsx 等办公文档解析使用 defusedxml 并拒绝 DOCTYPE/ENTITY 声明
7. 智能体问答只使用本工作区已授权数据：prompt 注入确定性摘要与检索片段，模型不可用时降级为规则摘要，从不调用未授权外部系统
8. 权限档位（`auto_approve` / `full_access`）只放宽人工审批，不绕过 RBAC、不放宽租户目录隔离、也不放开 `run_python`；无服务端派生的工作区声明时文件工具仍失败关闭
9. 子代理复用父代理已过滤的工具集，因此权限永远是父代理的子集；它共享而不是重置父执行的时间预算，并需技能白名单与 RBAC 双重授权
10. 版本快照存于租户目录之外（`.futureagent/versions`），模型的文件工具看不到也改不到；`list_files` 统一屏蔽 `.futureagent`
11. 用量数字只来自模型上报的 `usage_metadata`；未上报时不写记录也不计入调用数，避免把“未计量”伪装成“零消耗”；成本仅在 `core/pricing.py` 登记了单价时计算

## 11. 上线前必须完成

1. 配置真实模型供应商并在"模型中心"验证
2. 使用 PostgreSQL + S3 对象存储（PostgreSQL 部署同时启用 LangGraph 会话记忆与 pgvector 检索升级路径）
3. 配置恶意文件扫描、备份、TLS；多副本部署时在网关配置认证限流
4. 替换所有默认凭据和密钥

## 12. 功能路线图

对标分析见 `docs/workbuddy-gap-analysis.md`（历史快照：其中的汇报/经营智能体已按产品收敛移除，知识检索与其余能力保留）。已完成的 P0/P1 能力：智能体 LLM 化与知识检索、交付物中心、通知中心、消息分页与全局搜索、PDF 解析、看板拖拽/日历/评论、暗色模式、PWA、管理端运营闭环、认证限流、多 Agent 并行编排、本地 Qwen 向量召回（混合检索）、对话归档/重命名/删除、Markdown 渲染、会话吊销、CSV 导出。

近期补齐的 Agent 基础能力：五档运行模式（chat/plan/agent/goal/loop）、权限三档（默认/自动审批/完全访问）、用量统计（真实 token 与可选成本）、差异分析（版本快照与 diff）、子代理（显式开启的 `dispatch_subagent`）。

后续候选：前端 E2E 用例扩充、批次重试策略产品化、模型单价表按实际合约填写以启用成本核算。

### pgvector HNSW 调参

HNSW 索引参数由配置生成（迁移 20260902_17），查询宽度在线可调：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `HNSW_M` | 16 | 每节点连接数；越大召回越高、索引越大构建越慢 |
| `HNSW_EF_CONSTRUCTION` | 64 | 构建搜索宽度；越大索引质量越高 |
| `HNSW_EF_SEARCH` | 40 | 查询搜索宽度；在线可调 |

**20k 块 / 256 维 / 50 查询实测**（`scripts/benchmark_hnsw.py`）：精确扫描 recall 100% / p50 28.1ms；HNSW `ef_search=40` **recall 100% / p50 15.7ms**（约 2 倍提速）——默认值即均衡点。召回低于预期时加大 `HNSW_EF_SEARCH`；更换 embedding 模型后更新 `EMBEDDING_DIM` 并重跑迁移/重建索引。

## 许可证

MIT
