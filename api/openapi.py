"""面向产品使用者的中文 OpenAPI 文档配置。

接口路径、请求字段和响应结构仍以代码中的 REST API 为准；本模块只在
生成 OpenAPI 描述时补充中文分组、摘要与使用说明，避免为了文档展示而改变
任何运行时路由或认证逻辑。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


API_TITLE = "futureAgent 开放接口"
API_VERSION = "0.1.0"
API_DESCRIPTION = """
面向 futureAgent 用户端、管理员后台和受信任集成方的 REST 接口。

## 认证与工作区范围

1. 先调用「注册账号」或「登录」取得响应中的 `access_token`。
2. 对需要登录的接口，在 `Authorization` 请求头中使用
   `Bearer <access_token>`。
3. 对工作区相关接口，请始终传入 `X-Workspace-ID`。未传时服务会选择该账号最早
   加入的工作区，这只用于兼容旧客户端，不适合生产集成。
4. `refresh` 和 `logout` 使用同源、HttpOnly 的刷新 Cookie。非浏览器集成应在访问
   令牌到期前重新登录或由受控服务完成续期，不要把刷新 Cookie 写入日志或前端存储。

## 调用约定

- 所有路径均相对于当前 API 服务地址，例如 `/api/v1/workspaces`。
- 日期时间使用 ISO 8601 格式；所有标识符均由服务端生成。
- 除特别标注外，`401` 表示未登录或令牌失效，`403` 表示当前角色没有权限，`422`
  表示请求字段未通过校验。
- 智能助手执行接口会先检查模型可用性。上游模型没有通过可用性验证时会返回 `503`，
  不会伪造执行成功结果。

## 权限说明

接口权限由服务端根据登录账号、工作区成员身份和平台管理员身份判定。请勿向请求体
传入角色字段，也不要依赖前端隐藏按钮作为安全边界。

## 经营智能体与已授权数据接入

经营智能体接口用于将**已授权**的 OA、小程序、生产日报、企业机器人、系统导出或
受控中间件数据写入当前工作区，并生成规则预警、日报和老板任务。它不提供个人微信
聊天记录抓取、绕过登录、逆向接口或任意地址抓取能力。

- 老板智能体和私事员工智能体只允许工作区所有者访问；平台管理员不会自动获得私事
  数据访问权。
- 公事员工智能体只检索当前工作区中已授权的公事范围数据。
- 数据源创建或轮换时返回的接入令牌仅展示一次；集成方应将其保存到受控密钥系统，
  通过服务端请求提交，绝不能写入浏览器、README、审计日志或业务正文。
- 接入端点只接收已登记数据源的入站数据，不会根据数据源填写的地址发起出站网络请求。
- 日报生成按工作区和日期幂等；需要固定时段运行时，请由已认证的调度服务调用生成接口。

## 文档界面语言

`/docs` 与 `/redoc` 均由服务端从本 OpenAPI 描述生成中文接口目录，不加载第三方
Swagger UI 或 ReDoc，也不通过运行时 DOM 文本替换伪造翻译。接口路径、JSON 字段和
JSON Schema 保留技术名称，便于自动化工具和集成方直接调用。
""".strip()


OPENAPI_TAGS = [
    {
        "name": "系统状态",
        "description": "存活、就绪与依赖状态探针，供部署平台和运维检查使用。",
    },
    {
        "name": "账户与会话",
        "description": "账号注册、登录、访问令牌续期与当前登录态查询。",
    },
    {
        "name": "工作区与成员",
        "description": "工作区生命周期、成员邀请、角色调整与所有权转移。",
    },
    {
        "name": "项目与任务",
        "description": "项目、任务及任务动态的协作管理接口。",
    },
    {
        "name": "工作计划",
        "description": "工作模式的计划草稿、审批和步骤进度管理。",
    },
    {
        "name": "对话与智能助手",
        "description": "会话、消息、普通聊天和智能助手聊天接口。",
    },
    {
        "name": "经营智能体与数据接入",
        "description": "已授权业务数据接入、三类经营助手、规则预警、生产日报和老板任务。",
    },
    {
        "name": "受治理的任务执行",
        "description": "具备幂等、重试、取消、并发限制和审计能力的工作模式执行接口。",
    },
    {
        "name": "附件与预览",
        "description": "受工作区权限保护的附件上传、下载、列表与内容预览。",
    },
    {
        "name": "模型、技能与 MCP",
        "description": "模型可用性、技能配置和 MCP 服务发现；模型探测仅限平台管理员。",
    },
    {
        "name": "平台治理",
        "description": "平台级权限策略、运行配置、用户和工作区管理，仅限平台管理员。",
    },
    {
        "name": "审计与概览",
        "description": "工作区审计记录、平台审计记录和运营概览。",
    },
]


def _operation(summary: str, description: str, tag: str) -> dict[str, str]:
    return {"summary": summary, "description": description, "tag": tag}


OPERATION_DOCUMENTATION: dict[tuple[str, str], dict[str, str]] = {
    ("GET", "/"): _operation(
        "查看服务入口", "返回服务入口页面；未配置静态首页时返回服务与文档地址。", "系统状态"
    ),
    ("GET", "/api/v1/health"): _operation(
        "查看服务状态", "返回服务基本状态与当前运行环境，不检查数据库和对象存储。", "系统状态"
    ),
    ("GET", "/api/v1/health/live"): _operation(
        "存活探针", "仅确认 API 进程仍在运行，依赖服务恢复期间也可能返回成功。", "系统状态"
    ),
    ("GET", "/api/v1/health/ready"): _operation(
        "就绪探针", "检查数据库和当前附件存储后端；依赖异常时返回 503。", "系统状态"
    ),
    ("POST", "/api/v1/auth/register"): _operation(
        "注册账号", "创建账号及初始工作区，返回访问令牌并设置同源刷新 Cookie。", "账户与会话"
    ),
    ("POST", "/api/v1/auth/login"): _operation(
        "登录", "校验邮箱和密码，返回新的访问令牌并轮换同源刷新 Cookie。", "账户与会话"
    ),
    ("POST", "/api/v1/auth/refresh"): _operation(
        "续期访问令牌", "使用同源刷新 Cookie 轮换会话并返回新的访问令牌。", "账户与会话"
    ),
    ("POST", "/api/v1/auth/logout"): _operation(
        "退出登录", "撤销当前刷新会话并清除同源刷新 Cookie。", "账户与会话"
    ),
    ("GET", "/api/v1/auth/me"): _operation(
        "获取当前账号", "返回当前账号资料及其可访问的工作区列表。", "账户与会话"
    ),
    ("GET", "/api/v1/workspaces"): _operation(
        "列出工作区", "返回当前账号所属的全部工作区和对应成员角色。", "工作区与成员"
    ),
    ("POST", "/api/v1/workspaces"): _operation(
        "创建工作区", "以当前账号为所有者创建一个工作区。", "工作区与成员"
    ),
    ("PATCH", "/api/v1/workspaces/{workspace_id}"): _operation(
        "更新工作区", "更新工作区名称或套餐信息，需要工作区管理权限。", "工作区与成员"
    ),
    ("GET", "/api/v1/workspaces/{workspace_id}/members"): _operation(
        "列出工作区成员", "查看指定工作区的成员与角色，需要该工作区访问权限。", "工作区与成员"
    ),
    ("POST", "/api/v1/workspaces/{workspace_id}/members"): _operation(
        "添加工作区成员", "按已注册账号的邮箱添加成员，需要工作区管理权限。", "工作区与成员"
    ),
    ("PATCH", "/api/v1/workspaces/{workspace_id}/members/{member_id}"): _operation(
        "更新成员角色", "调整成员角色，需要工作区管理权限。", "工作区与成员"
    ),
    ("DELETE", "/api/v1/workspaces/{workspace_id}/members/{member_id}"): _operation(
        "移除工作区成员", "将成员移出工作区，需要工作区管理权限。", "工作区与成员"
    ),
    ("POST", "/api/v1/workspaces/{workspace_id}/transfer-owner"): _operation(
        "转移工作区所有权", "将所有权交给指定成员，需要当前所有者权限。", "工作区与成员"
    ),
    ("GET", "/api/v1/projects"): _operation(
        "列出项目", "返回当前工作区的项目列表。", "项目与任务"
    ),
    ("POST", "/api/v1/projects"): _operation(
        "创建项目", "在当前工作区创建项目，需要工作区管理权限。", "项目与任务"
    ),
    ("PATCH", "/api/v1/projects/{project_id}"): _operation(
        "更新项目", "更新项目名称、描述、颜色或状态，需要工作区管理权限。", "项目与任务"
    ),
    ("GET", "/api/v1/tasks"): _operation(
        "列出任务", "按当前工作区返回任务，可按项目筛选。", "项目与任务"
    ),
    ("POST", "/api/v1/tasks"): _operation(
        "创建任务", "在当前工作区的项目中创建任务，需要工作区管理权限。", "项目与任务"
    ),
    ("PATCH", "/api/v1/tasks/{task_id}"): _operation(
        "更新任务", "更新任务内容、状态、优先级、负责人、标签或排序。", "项目与任务"
    ),
    ("GET", "/api/v1/tasks/{task_id}/activity"): _operation(
        "查看任务动态", "返回任务关联的工作计划、执行和附件等审计动态。", "项目与任务"
    ),
    ("GET", "/api/v1/tasks/{task_id}/plan"): _operation(
        "获取工作计划", "返回指定任务的工作模式计划及其步骤。", "工作计划"
    ),
    ("PUT", "/api/v1/tasks/{task_id}/plan"): _operation(
        "保存工作计划", "创建或更新计划草稿；已开始执行的计划不能直接覆盖。", "工作计划"
    ),
    ("POST", "/api/v1/tasks/{task_id}/plan/approve"): _operation(
        "审批工作计划", "审批草稿计划，使其可以进入受治理的任务执行流程。", "工作计划"
    ),
    ("PATCH", "/api/v1/tasks/{task_id}/plan/steps/{step_id}"): _operation(
        "更新计划步骤", "更新步骤状态、执行摘要或负责人。", "工作计划"
    ),
    ("GET", "/api/v1/conversations"): _operation(
        "列出对话", "返回当前工作区中的对话，可按项目筛选。", "对话与智能助手"
    ),
    ("POST", "/api/v1/conversations"): _operation(
        "创建对话", "在当前工作区创建新的普通对话或项目关联对话。", "对话与智能助手"
    ),
    ("PATCH", "/api/v1/conversations/{conversation_id}"): _operation(
        "更新对话", "更新对话标题或归档状态。", "对话与智能助手"
    ),
    ("GET", "/api/v1/conversations/{conversation_id}/messages"): _operation(
        "列出对话消息", "返回指定对话的历史消息。", "对话与智能助手"
    ),
    ("POST", "/api/v1/chat/completions"): _operation(
        "发送普通聊天请求", "向选定模型发送聊天请求，并以服务器发送事件流返回结果。", "对话与智能助手"
    ),
    ("POST", "/api/v1/chat/agent"): _operation(
        "发送智能助手聊天请求", "按选定模型、技能和 MCP 服务发起智能助手对话，并以事件流返回结果。", "对话与智能助手"
    ),
    ("GET", "/api/v1/business/dashboard"): _operation(
        "查看经营助手概览", "返回当前账号有权查看的数据源、预警、日报和任务汇总；不会混入私事数据。", "经营智能体与数据接入"
    ),
    ("GET", "/api/v1/business/assistants"): _operation(
        "列出可访问的经营助手", "按当前账号返回老板、私事或公事助手；私有助手不会向非所有者暴露。", "经营智能体与数据接入"
    ),
    ("GET", "/api/v1/business/data-sources"): _operation(
        "列出已授权数据源", "返回当前工作区可见的数据源元数据，不返回接入令牌或供应商密钥。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/data-sources"): _operation(
        "登记数据源", "登记已授权数据源并一次性返回入站接入凭据；明文接入令牌不会被持久化或再次返回。", "经营智能体与数据接入"
    ),
    ("GET", "/api/v1/business/alerts"): _operation(
        "列出经营预警", "返回当前账号有权处理的预警及其来源、级别和处理状态。", "经营智能体与数据接入"
    ),
    ("GET", "/api/v1/business/daily-reports"): _operation(
        "列出生产日报", "返回基于已授权公事数据生成、可按日期追溯的日报。", "经营智能体与数据接入"
    ),
    ("GET", "/api/v1/business/tasks"): _operation(
        "列出老板任务", "老板查看全部下达任务；员工仅查看分配给自己的任务。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/assistants"): _operation(
        "创建经营助手", "创建公司公事助手或老板私有助手；私有助手只能由当前工作区所有者创建。", "经营智能体与数据接入"
    ),
    ("PATCH", "/api/v1/business/assistants/{assistant_id}"): _operation(
        "更新经营助手", "更新助手名称、说明或启用状态；服务端再次校验助手的私有归属。", "经营智能体与数据接入"
    ),
    ("GET", "/api/v1/business/assistants/{assistant_id}/messages"): _operation(
        "查看助手对话历史", "仅返回当前用户在该助手中的历史消息；公事助手也不会共享员工之间的对话。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/assistants/{assistant_id}/chat"): _operation(
        "查询经营助手", "基于当前权限范围内的已授权记录生成确定性摘要，不调用未验证的外部模型。", "经营智能体与数据接入"
    ),
    ("PATCH", "/api/v1/business/data-sources/{source_id}"): _operation(
        "更新数据源配置", "更新名称、授权说明、地址元数据或启用状态；不得通过此接口保存密钥。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/data-sources/{source_id}/rotate-ingest-token"): _operation(
        "轮换接入令牌", "为 API 或 Webhook 数据源轮换令牌；新令牌仅在本次响应中展示一次。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/data-sources/{source_id}/records"): _operation(
        "提交业务记录", "由已登录且有管理权限的用户提交一条已授权业务记录，并触发适用的规则预警。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/data-sources/{source_id}/records/batch"): _operation(
        "批量提交业务记录", "通过受控导入批量提交最多 100 条业务记录，返回入库与预警结果。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/ingest/{source_id}"): _operation(
        "接收授权接口推送", "使用一次性发放后受控保存的入站令牌接收一条记录；服务不会向数据源地址发起出站请求。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/ingest/{source_id}/batch"): _operation(
        "批量接收授权接口推送", "使用入站令牌接收最多 100 条业务记录，并按外部编号去重。", "经营智能体与数据接入"
    ),
    ("GET", "/api/v1/business/records"): _operation(
        "查看业务记录", "返回当前账号可管理的原始记录；公司范围记录仅向工作区管理者开放。", "经营智能体与数据接入"
    ),
    ("GET", "/api/v1/business/alert-rules"): _operation(
        "列出预警规则", "返回当前账号可见的关键字预警规则，包含系统默认的生产、订单、设备、交期和审批规则。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/alert-rules"): _operation(
        "创建预警规则", "创建按记录类型和关键字匹配的预警规则；私有规则仅限老板范围。", "经营智能体与数据接入"
    ),
    ("PATCH", "/api/v1/business/alert-rules/{rule_id}"): _operation(
        "更新预警规则", "更新规则名称、关键字、级别或启用状态，并保持原有数据范围不变。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/alerts"): _operation(
        "登记人工预警", "针对当前工作区内的已授权来源或记录登记人工预警，所有关联关系会在服务端校验。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/alerts/{alert_id}/acknowledge"): _operation(
        "确认经营预警", "确认当前账号有权访问的未解决预警，并记录处理人和时间。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/alerts/{alert_id}/resolve"): _operation(
        "解决经营预警", "将当前账号有权访问的预警标为已解决，并保留处理审计。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/daily-reports"): _operation(
        "生成生产日报", "按日期幂等生成公司范围的规则日报；私事数据会被明确排除。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/daily-reports/generate"): _operation(
        "按日期生成生产日报", "按请求日期汇总公司范围的业务记录与未闭环预警，生成前仍需人工复核。", "经营智能体与数据接入"
    ),
    ("POST", "/api/v1/business/tasks"): _operation(
        "下达老板任务", "仅当前工作区所有者可创建任务；负责人必须是同一工作区成员。", "经营智能体与数据接入"
    ),
    ("PATCH", "/api/v1/business/tasks/{task_id}"): _operation(
        "更新老板任务", "老板可更新任务全部字段，负责人仅能更新自己的状态和进度说明。", "经营智能体与数据接入"
    ),
    ("GET", "/api/v1/tasks/{task_id}/runs"): _operation(
        "列出任务执行记录", "返回任务的受治理执行记录、重试谱系与当前状态。", "受治理的任务执行"
    ),
    ("POST", "/api/v1/tasks/{task_id}/runs/{run_id}/cancel"): _operation(
        "取消任务执行", "请求取消仍在进行中的任务执行，并写入审计记录。", "受治理的任务执行"
    ),
    ("POST", "/api/v1/tasks/{task_id}/execute"): _operation(
        "执行已审批的工作计划", "发起受治理的智能助手执行；支持幂等键、失败重试、并发限制和取消。", "受治理的任务执行"
    ),
    ("POST", "/api/v1/attachments"): _operation(
        "上传附件", "上传受当前工作区权限保护的附件，可关联任务或对话。", "附件与预览"
    ),
    ("GET", "/api/v1/attachments"): _operation(
        "列出附件", "按当前工作区、任务或对话筛选附件。", "附件与预览"
    ),
    ("GET", "/api/v1/attachments/{attachment_id}/download"): _operation(
        "下载附件", "在通过工作区权限校验后下载原始附件内容。", "附件与预览"
    ),
    ("GET", "/api/v1/attachments/{attachment_id}/preview"): _operation(
        "预览附件", "返回可安全预览的文本、图片或文档提取内容。", "附件与预览"
    ),
    ("GET", "/api/v1/models"): _operation(
        "列出模型", "返回当前工作区允许使用的模型及其可用性状态。", "模型、技能与 MCP"
    ),
    ("POST", "/api/v1/models/{model_id}/probe"): _operation(
        "探测模型可用性", "向上游执行最小探测并记录结果，仅限平台管理员。", "模型、技能与 MCP"
    ),
    ("GET", "/api/v1/skills"): _operation(
        "列出技能", "返回当前工作区可用的智能助手技能。", "模型、技能与 MCP"
    ),
    ("POST", "/api/v1/skills"): _operation(
        "创建技能", "创建工作区技能，需要工作区管理权限。", "模型、技能与 MCP"
    ),
    ("PUT", "/api/v1/skills/{skill_name}"): _operation(
        "更新技能", "更新指定工作区技能，需要工作区管理权限。", "模型、技能与 MCP"
    ),
    ("DELETE", "/api/v1/skills/{skill_name}"): _operation(
        "删除技能", "删除指定工作区技能，需要工作区管理权限。", "模型、技能与 MCP"
    ),
    ("GET", "/api/v1/mcp/servers"): _operation(
        "列出 MCP 服务", "返回当前工作区已允许选择的 MCP 服务状态。", "模型、技能与 MCP"
    ),
    ("GET", "/api/v1/auth/policies"): _operation(
        "列出平台权限策略", "返回平台授权策略，仅限平台管理员。", "平台治理"
    ),
    ("POST", "/api/v1/auth/policies"): _operation(
        "新增平台权限策略", "添加一条平台授权策略，仅限平台管理员。", "平台治理"
    ),
    ("DELETE", "/api/v1/auth/policies"): _operation(
        "删除平台权限策略", "删除一条平台授权策略，仅限平台管理员。", "平台治理"
    ),
    ("GET", "/api/v1/settings"): _operation(
        "查看平台运行设置", "返回经过脱敏的运行设置，仅限平台管理员。", "平台治理"
    ),
    ("GET", "/api/v1/admin/overview"): _operation(
        "查看平台运营概览", "返回用户、工作区、任务、模型和运行状态的汇总，仅限平台管理员。", "审计与概览"
    ),
    ("GET", "/api/v1/dashboard"): _operation(
        "查看工作区概览", "返回当前工作区的项目、任务、对话与执行概览。", "审计与概览"
    ),
    ("GET", "/api/v1/admin/users"): _operation(
        "列出平台用户", "返回平台用户列表，仅限平台管理员。", "平台治理"
    ),
    ("PATCH", "/api/v1/admin/users/{user_id}"): _operation(
        "更新平台用户", "更新用户名称、启用状态或平台管理员身份，仅限平台管理员。", "平台治理"
    ),
    ("GET", "/api/v1/admin/workspaces"): _operation(
        "列出平台工作区", "返回全部工作区及成员统计，仅限平台管理员。", "平台治理"
    ),
    ("GET", "/api/v1/audit-events"): _operation(
        "查看工作区审计记录", "返回当前工作区的审计记录。", "审计与概览"
    ),
    ("GET", "/api/v1/admin/audit-events"): _operation(
        "查看平台审计记录", "返回全平台审计记录，仅限平台管理员。", "审计与概览"
    ),
}

# 经营智能体的接入端点同时面向产品页面和受控中间件。显式列出每项操作，
# 避免新业务路由在中文目录中退化为无意义的通用文案。
OPERATION_DOCUMENTATION.update(
    {
        ("GET", "/api/v1/business/dashboard"): _operation(
            "查看经营助手概览",
            "返回当前账号可见的数据源、预警、日报和任务汇总；私事数据不会混入。",
            "经营智能体与数据接入",
        ),
        ("GET", "/api/v1/business/assistants"): _operation(
            "列出可访问的经营助手",
            "按当前账号返回老板、私事或公事助手；私有助手不向非所有者暴露。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/assistants"): _operation(
            "创建经营助手",
            "创建指定范围的经营助手。老板和私事助手仅限工作区所有者创建。",
            "经营智能体与数据接入",
        ),
        ("PATCH", "/api/v1/business/assistants/{assistant_id}"): _operation(
            "更新经营助手",
            "更新助手名称、说明或启停状态，服务端校验助手范围和身份。",
            "经营智能体与数据接入",
        ),
        ("GET", "/api/v1/business/assistants/{assistant_id}/messages"): _operation(
            "读取经营助手历史",
            "读取当前用户在该助手中的已保存对话；公事助手也按用户隔离历史。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/assistants/{assistant_id}/chat"): _operation(
            "查询经营助手",
            "基于当前账号有权读取的已授权记录生成确定性摘要，不调用未验证的外部模型。",
            "经营智能体与数据接入",
        ),
        ("GET", "/api/v1/business/data-sources"): _operation(
            "列出已授权数据源",
            "返回可见数据源的非敏感状态信息，不返回接口地址、授权文本、令牌或令牌哈希。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/data-sources"): _operation(
            "登记数据源",
            "登记已授权的 API、导出、中间件或企业机器人数据源；入站令牌仅在本响应展示一次。",
            "经营智能体与数据接入",
        ),
        ("PATCH", "/api/v1/business/data-sources/{source_id}"): _operation(
            "更新数据源",
            "更新名称、最小授权说明、地址元数据或启停状态；服务端不会主动请求保存的地址。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/data-sources/{source_id}/rotate-ingest-token"): _operation(
            "轮换数据接入令牌",
            "吊销旧令牌并一次性返回新令牌，仅适用于 API 或 Webhook 类型数据源。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/data-sources/{source_id}/records"): _operation(
            "提交已认证业务记录",
            "由有管理权限的账号手工或受控服务写入一条业务记录，并触发适用的规则预警。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/data-sources/{source_id}/records/batch"): _operation(
            "批量提交已认证业务记录",
            "批量写入同一数据源的业务记录；按外部标识去重并保留采集批次。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/ingest/{source_id}"): _operation(
            "通过接入令牌写入业务记录",
            "供已授权中间件调用。必须提供数据源一次性发放的接入令牌，不接受未登记来源。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/ingest/{source_id}/batch"): _operation(
            "通过接入令牌批量写入业务记录",
            "供已授权中间件批量调用；同一数据源的外部标识重复提交不会重复入库。",
            "经营智能体与数据接入",
        ),
        ("GET", "/api/v1/business/records"): _operation(
            "查看业务记录",
            "返回当前账号可查看的可追溯记录；原始公司记录仅向工作区管理者开放。",
            "经营智能体与数据接入",
        ),
        ("GET", "/api/v1/business/alert-rules"): _operation(
            "列出预警规则",
            "返回当前账号有权查看的关键字和字段规则。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/alert-rules"): _operation(
            "创建预警规则",
            "按数据范围创建关键字预警规则，私有范围仍只允许对应所有者操作。",
            "经营智能体与数据接入",
        ),
        ("PATCH", "/api/v1/business/alert-rules/{rule_id}"): _operation(
            "更新预警规则",
            "更新规则名称、关键字、级别或启停状态。",
            "经营智能体与数据接入",
        ),
        ("GET", "/api/v1/business/alerts"): _operation(
            "列出经营预警",
            "返回当前账号可见的预警及其级别、状态和来源关联。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/alerts"): _operation(
            "创建人工预警",
            "为已授权记录或数据源创建人工预警；跨工作区关联会被拒绝。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/alerts/{alert_id}/acknowledge"): _operation(
            "确认经营预警",
            "确认可处理的预警并写入确认人和时间。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/alerts/{alert_id}/resolve"): _operation(
            "解决经营预警",
            "将可处理的预警标记为已解决并保留处理轨迹。",
            "经营智能体与数据接入",
        ),
        ("GET", "/api/v1/business/daily-reports"): _operation(
            "列出生产日报",
            "返回仅基于公司范围已授权记录生成的日报，私有记录明确被排除。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/daily-reports"): _operation(
            "生成生产日报",
            "按工作区和日期幂等生成生产日报；固定时段可由受控调度服务调用。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/daily-reports/generate"): _operation(
            "生成生产日报",
            "按工作区和日期幂等生成生产日报；固定时段可由受控调度服务调用。",
            "经营智能体与数据接入",
        ),
        ("GET", "/api/v1/business/tasks"): _operation(
            "列出老板任务",
            "老板查看自己下达的任务，成员仅查看分配给自己的任务。",
            "经营智能体与数据接入",
        ),
        ("POST", "/api/v1/business/tasks"): _operation(
            "下达老板任务",
            "仅工作区所有者可下达任务并指定当前工作区负责人。",
            "经营智能体与数据接入",
        ),
        ("PATCH", "/api/v1/business/tasks/{task_id}"): _operation(
            "更新老板任务",
            "老板可调整任务；负责人仅可更新分配给自己的状态和进度说明。",
            "经营智能体与数据接入",
        ),
    }
)


def _fallback_tag(path: str) -> str:
    """为新增但尚未写专属文案的路由提供中文分组。"""
    if path.startswith("/api/v1/business"):
        return "经营智能体与数据接入"
    if path.startswith("/api/v1/auth/"):
        return "账户与会话"
    if path.startswith("/api/v1/workspaces/") or path == "/api/v1/workspaces":
        return "工作区与成员"
    if path.startswith("/api/v1/projects"):
        return "项目与任务"
    if path.startswith("/api/v1/tasks"):
        return "项目与任务"
    if path.startswith("/api/v1/conversations") or path.startswith("/api/v1/chat/"):
        return "对话与智能助手"
    if path.startswith("/api/v1/attachments"):
        return "附件与预览"
    if path.startswith("/api/v1/models") or path.startswith("/api/v1/skills") or path.startswith("/api/v1/mcp"):
        return "模型、技能与 MCP"
    if path.startswith("/api/v1/admin/") or path == "/api/v1/settings":
        return "平台治理"
    if path.startswith("/api/v1/audit") or path == "/api/v1/dashboard":
        return "审计与概览"
    return "系统状态"


def _localize_parameters(operation: dict[str, Any]) -> None:
    for parameter in operation.get("parameters", []):
        if parameter.get("name") == "X-Workspace-ID":
            parameter["description"] = (
                "目标工作区 ID。生产客户端应始终显式传入，避免服务端按成员加入时间自动选择工作区。"
            )
        elif parameter.get("name") == "futureagent_refresh":
            parameter["description"] = "同源浏览器自动维护的 HttpOnly 刷新 Cookie，无需手动填写。"


def _localize_responses(operation: dict[str, Any]) -> None:
    for response in operation.get("responses", {}).values():
        if response.get("description") == "Successful Response":
            response["description"] = "请求成功"
        elif response.get("description") == "Validation Error":
            response["description"] = "请求参数校验失败"


def build_openapi_schema(app: FastAPI) -> dict[str, Any]:
    """构建中文说明，不改变原始路由、字段名或 OpenAPI 地址。"""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=API_TITLE,
        version=API_VERSION,
        description=API_DESCRIPTION,
        routes=app.routes,
        tags=OPENAPI_TAGS,
    )
    schema["info"]["contact"] = {"name": "futureAgent 平台管理员"}

    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            metadata = OPERATION_DOCUMENTATION.get((method.upper(), path))
            if metadata:
                operation["summary"] = metadata["summary"]
                operation["description"] = metadata["description"]
                operation["tags"] = [metadata["tag"]]
            else:
                tag = _fallback_tag(path)
                operation["summary"] = f"{tag}相关操作"
                operation["description"] = f"此接口属于「{tag}」，请结合请求字段和响应结构调用。"
                operation["tags"] = [tag]
            _localize_parameters(operation)
            _localize_responses(operation)

    components = schema.setdefault("components", {})
    for scheme in components.get("securitySchemes", {}).values():
        if scheme.get("type") == "http" and scheme.get("scheme") == "bearer":
            scheme["description"] = (
                "在 `Authorization` 请求头中使用 `Bearer <access_token>`；"
                "访问令牌来自登录或注册响应。"
            )
    for schema_name, title, description in (
        ("HTTPValidationError", "请求参数校验错误", "请求参数未通过服务端校验。"),
        ("ValidationError", "字段校验错误", "单个请求字段的校验错误明细。"),
    ):
        component = components.get("schemas", {}).get(schema_name)
        if component:
            component["title"] = title
            component["description"] = description

    app.openapi_schema = schema
    return app.openapi_schema
