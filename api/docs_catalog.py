"""不依赖第三方前端的中文 OpenAPI 接口目录渲染器。"""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any


HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
METHOD_LABELS = {
    "get": "读取",
    "post": "创建或执行",
    "put": "整体更新",
    "patch": "部分更新",
    "delete": "删除",
    "head": "检查头信息",
    "options": "查询能力",
}
PARAMETER_LOCATIONS = {
    "path": "路径参数",
    "query": "查询参数",
    "header": "请求头",
    "cookie": "Cookie",
}


def _inline(value: Any) -> str:
    """转义来自 OpenAPI 的文本，同时保留反引号技术字段的视觉层级。"""
    text = str(value or "")
    parts = re.split(r"(`[^`]+`)", text)
    return "".join(
        f"<code>{escape(part[1:-1])}</code>" if part.startswith("`") and part.endswith("`") else escape(part)
        for part in parts
    )


def _markdown_description(value: Any) -> str:
    """只支持接口说明实际使用到的轻量 Markdown，不信任任何原始 HTML。"""
    blocks: list[str] = []
    list_items: list[str] = []

    def flush_list() -> None:
        if list_items:
            blocks.append("<ol>" + "".join(list_items) + "</ol>")
            list_items.clear()

    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            flush_list()
            continue
        if line.startswith("## "):
            flush_list()
            blocks.append(f"<h3>{_inline(line[3:])}</h3>")
            continue
        numbered_item = re.match(r"^\d+\.\s+(.+)$", line)
        bullet_item = re.match(r"^-\s+(.+)$", line)
        if numbered_item or bullet_item:
            list_items.append(f"<li>{_inline((numbered_item or bullet_item).group(1))}</li>")
            continue
        flush_list()
        blocks.append(f"<p>{_inline(line)}</p>")
    flush_list()
    return "".join(blocks)


def _json_block(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return f"<pre><code>{escape(rendered)}</code></pre>"


def _schema_label(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "未标注"
    reference = schema.get("$ref")
    if isinstance(reference, str):
        return reference.rsplit("/", 1)[-1]
    value_type = schema.get("type")
    if isinstance(value_type, str):
        return value_type
    if "oneOf" in schema:
        return "多种结构之一"
    if "anyOf" in schema:
        return "可选结构"
    return "对象"


def _parameter_table(operation: dict[str, Any]) -> str:
    parameters = operation.get("parameters", [])
    if not isinstance(parameters, list) or not parameters:
        return ""

    rows: list[str] = []
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        schema = parameter.get("schema", {})
        enum = schema.get("enum") if isinstance(schema, dict) else None
        enum_text = ""
        if isinstance(enum, list) and enum:
            enum_text = f"<br><small>可选值：{_inline('、'.join(map(str, enum)))}</small>"
        required = "必填" if parameter.get("required") else "可选"
        location = PARAMETER_LOCATIONS.get(str(parameter.get("in")), str(parameter.get("in", "参数")))
        rows.append(
            "<tr>"
            f"<td><code>{escape(str(parameter.get('name', '')))}</code></td>"
            f"<td>{escape(location)}</td>"
            f"<td>{required}</td>"
            f"<td>{escape(_schema_label(schema))}{enum_text}</td>"
            f"<td>{_inline(parameter.get('description') or '—')}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    return (
        "<section class=\"parameter-section\"><h4>请求参数</h4>"
        "<div class=\"table-scroll\"><table><thead><tr>"
        "<th>字段</th><th>位置</th><th>是否必填</th><th>数据类型</th><th>说明</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div></section>"
    )


def _access_note(operation: dict[str, Any], security_schemes: dict[str, Any]) -> str:
    security = operation.get("security")
    if isinstance(security, list) and security:
        names = [name for rule in security if isinstance(rule, dict) for name in rule]
        descriptions = [
            str(security_schemes.get(name, {}).get("description", ""))
            for name in names
            if isinstance(security_schemes.get(name), dict)
        ]
        detail = next((item for item in descriptions if item), "需要有效访问令牌。")
        return f"<p class=\"access protected\"><strong>认证要求：</strong>{_inline(detail)}</p>"
    parameters = operation.get("parameters", [])
    if isinstance(parameters, list) and any(
        isinstance(item, dict) and item.get("in") == "cookie" for item in parameters
    ):
        return "<p class=\"access cookie\"><strong>认证要求：</strong>需要同源刷新 Cookie。</p>"
    return "<p class=\"access public\"><strong>认证要求：</strong>无需访问令牌。</p>"


def _technical_details(operation: dict[str, Any], *, expanded: bool) -> str:
    parts: list[str] = []
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        required = "必填" if request_body.get("required") else "可选"
        parts.append(
            "<section><h4>请求体</h4>"
            f"<p>{required}。{_inline(request_body.get('description') or '请按下列 JSON Schema 组织请求体。')}</p>"
            + _json_block(request_body.get("content", {}))
            + "</section>"
        )

    responses = operation.get("responses", {})
    if isinstance(responses, dict):
        response_rows = []
        for status_code, response in responses.items():
            if not isinstance(response, dict):
                continue
            response_rows.append(
                "<li>"
                f"<code>{escape(str(status_code))}</code>：{_inline(response.get('description') or '未说明')}"
                + (_json_block(response["content"]) if response.get("content") else "")
                + "</li>"
            )
        if response_rows:
            parts.append("<section><h4>响应</h4><ul class=\"response-list\">" + "".join(response_rows) + "</ul></section>")

    if not parts:
        return ""
    open_attribute = " open" if expanded else ""
    return (
        f"<details class=\"technical-details\"{open_attribute}>"
        "<summary>请求与响应技术数据</summary>"
        + "".join(parts)
        + "</details>"
    )


def _operation_card(
    path: str,
    method: str,
    operation: dict[str, Any],
    security_schemes: dict[str, Any],
    *,
    index: int,
    detailed: bool,
) -> str:
    method_label = METHOD_LABELS.get(method, "接口操作")
    summary = operation.get("summary") or "接口操作"
    description = operation.get("description") or "暂无接口说明。"
    parameters = _parameter_table(operation)
    technical = _technical_details(operation, expanded=detailed)
    return (
        f"<article class=\"operation\" id=\"operation-{index}\">"
        "<header class=\"operation-header\">"
        f"<span class=\"method method-{escape(method)}\">{escape(method.upper())}</span>"
        f"<div><p class=\"method-label\">{escape(method_label)}</p><h3>{_inline(summary)}</h3></div>"
        "</header>"
        f"<p class=\"path\"><code>{escape(path)}</code></p>"
        f"<p class=\"operation-description\">{_inline(description)}</p>"
        + _access_note(operation, security_schemes)
        + parameters
        + technical
        + "</article>"
    )


def _model_catalog(schema: dict[str, Any], *, expanded: bool) -> str:
    models = schema.get("components", {}).get("schemas", {})
    if not isinstance(models, dict) or not models:
        return ""
    items = "".join(
        f"<details class=\"model\"><summary><code>{escape(str(name))}</code>"
        f"：{_inline(model.get('title') if isinstance(model, dict) else '数据模型')}</summary>"
        f"{_json_block(model)}</details>"
        for name, model in models.items()
    )
    open_attribute = " open" if expanded else ""
    return (
        f"<section class=\"models\"><details{open_attribute}><summary>数据模型与 JSON Schema</summary>"
        "<p>字段名和 JSON Schema 保持技术名称，供代码生成、联调和自动化工具使用。</p>"
        + items
        + "</details></section>"
    )


def _catalog_styles() -> str:
    return """
    :root { color-scheme: light; font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; color: #172033; background: #f4f7fb; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #f4f7fb; line-height: 1.6; }
    a { color: #175cd3; text-decoration: none; }
    a:hover { text-decoration: underline; }
    code { font-family: Consolas, "SFMono-Regular", monospace; font-size: .91em; overflow-wrap: anywhere; }
    pre { margin: .75rem 0 0; padding: 1rem; overflow: auto; border-radius: 10px; background: #111827; color: #e5edf9; font-size: .81rem; line-height: 1.48; }
    .site-header { padding: 2.7rem max(1.25rem, calc((100% - 1180px) / 2)); background: linear-gradient(125deg, #122a57, #175cd3); color: #fff; }
    .eyebrow { margin: 0 0 .45rem; font-size: .86rem; letter-spacing: .08em; opacity: .82; }
    h1 { margin: 0; font-size: clamp(1.8rem, 4vw, 2.8rem); line-height: 1.2; }
    .site-header > p:last-child { max-width: 760px; margin: .8rem 0 0; color: #e6efff; }
    main { width: min(1180px, calc(100% - 2.5rem)); margin: 1.6rem auto 4rem; }
    .toolbar, .intro, .tag, .models { border: 1px solid #dbe5f3; border-radius: 14px; background: #fff; box-shadow: 0 4px 16px rgb(31 66 135 / 6%); }
    .toolbar { display: flex; flex-wrap: wrap; gap: .8rem 1.25rem; align-items: center; padding: 1rem 1.2rem; }
    .toolbar a { font-weight: 700; }
    .toolbar .current { color: #1e293b; }
    .toolbar .download { margin-left: auto; padding: .45rem .75rem; border-radius: 8px; color: #fff; background: #175cd3; }
    .intro { margin-top: 1.1rem; padding: 1.35rem 1.5rem; }
    .intro h2, .tag > h2 { margin-top: 0; color: #102a56; }
    .intro h3 { margin: 1.15rem 0 .25rem; font-size: 1rem; color: #243b64; }
    .intro p { margin: .45rem 0; }
    .intro ol { margin: .35rem 0; padding-left: 1.3rem; }
    .notice { margin: 1rem 0 0; padding: .8rem 1rem; border-left: 4px solid #175cd3; border-radius: 6px; background: #eff6ff; color: #173b76; }
    .tag-nav { display: flex; flex-wrap: wrap; gap: .55rem; margin: 1.25rem 0; }
    .tag-nav a { padding: .38rem .7rem; border: 1px solid #bed3f3; border-radius: 999px; background: #fff; font-size: .9rem; }
    .tag { margin: 1.4rem 0; padding: 1.35rem; scroll-margin-top: 1rem; }
    .tag > p { margin-top: -.5rem; color: #5a6a85; }
    .operation { margin-top: 1rem; padding: 1.15rem; border: 1px solid #e3eaf4; border-radius: 12px; background: #fbfdff; scroll-margin-top: 1rem; }
    .operation-header { display: flex; gap: .85rem; align-items: flex-start; }
    .operation-header h3 { margin: -.1rem 0 0; color: #172033; font-size: 1.08rem; }
    .method { min-width: 4.7rem; padding: .23rem .45rem; border-radius: 6px; text-align: center; color: #fff; font-weight: 800; font-size: .84rem; }
    .method-get { background: #147a4b; }.method-post { background: #175cd3; }.method-put { background: #7e4bb6; }.method-patch { background: #b54708; }.method-delete { background: #b42318; }.method-head, .method-options { background: #475467; }
    .method-label { margin: 0 0 .1rem; color: #667085; font-size: .78rem; }
    .path { margin: .75rem 0 .35rem; color: #344054; }
    .operation-description { margin: .35rem 0 .7rem; }
    .access { margin: .7rem 0; padding: .55rem .75rem; border-radius: 7px; font-size: .94rem; }.access.protected { background: #fff4e5; color: #7a3e00; }.access.cookie { background: #f1f5ff; color: #25428a; }.access.public { background: #ecfdf3; color: #09613a; }
    h4 { margin: 1rem 0 .45rem; color: #344054; font-size: .96rem; }.table-scroll { overflow-x: auto; } table { width: 100%; border-collapse: collapse; min-width: 680px; font-size: .9rem; } th, td { padding: .6rem; border: 1px solid #e2e8f0; vertical-align: top; text-align: left; } th { background: #f3f6fa; color: #344054; } small { color: #667085; }
    details { margin-top: .85rem; } summary { cursor: pointer; color: #175cd3; font-weight: 700; } .technical-details { padding: .8rem 1rem; border: 1px solid #dbe5f3; border-radius: 8px; background: #f8fbff; }.technical-details section + section { margin-top: 1rem; }.response-list { margin: 0; padding-left: 1.25rem; }.response-list li + li { margin-top: .6rem; }
    .models { margin-top: 1.4rem; padding: 1.2rem; }.models > details > summary { font-size: 1.05rem; }.model { padding: .7rem 0; border-top: 1px solid #e5eaf1; }.model summary { color: #344054; }
    footer { width: min(1180px, calc(100% - 2.5rem)); margin: 0 auto 2rem; color: #667085; font-size: .86rem; }
    @media (max-width: 620px) { main, footer { width: min(100% - 1.5rem, 1180px); }.site-header { padding: 2rem 1rem; }.tag, .intro, .operation { padding: 1rem; }.toolbar .download { margin-left: 0; }.operation-header { gap: .6rem; }.method { min-width: 4.2rem; } }
    """


def render_api_catalog(
    schema: dict[str, Any],
    *,
    openapi_url: str,
    compact_catalog_url: str,
    detailed_catalog_url: str,
    detailed: bool,
) -> str:
    """基于实时 OpenAPI schema 渲染静态、可审计的中文接口目录。"""
    tag_definitions = [item for item in schema.get("tags", []) if isinstance(item, dict)]
    tag_descriptions = {
        str(item.get("name")): str(item.get("description", ""))
        for item in tag_definitions
        if item.get("name")
    }
    grouped_operations: dict[str, list[tuple[str, str, dict[str, Any]]]] = {
        name: [] for name in tag_descriptions
    }
    for path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            tags = operation.get("tags")
            tag_name = str(tags[0]) if isinstance(tags, list) and tags else "未分组接口"
            grouped_operations.setdefault(tag_name, []).append((str(path), method, operation))
            tag_descriptions.setdefault(tag_name, "尚未填写分组说明。")

    ordered_tags = [name for name in tag_descriptions if grouped_operations.get(name)]
    operation_count = sum(len(grouped_operations[name]) for name in ordered_tags)
    nav = "".join(
        f"<a href=\"#tag-{index}\">{_inline(name)}（{len(grouped_operations[name])}）</a>"
        for index, name in enumerate(ordered_tags, start=1)
    )
    security_schemes = schema.get("components", {}).get("securitySchemes", {})
    if not isinstance(security_schemes, dict):
        security_schemes = {}

    groups: list[str] = []
    operation_index = 0
    for tag_index, tag_name in enumerate(ordered_tags, start=1):
        cards = []
        for path, method, operation in grouped_operations[tag_name]:
            operation_index += 1
            cards.append(
                _operation_card(
                    path,
                    method,
                    operation,
                    security_schemes,
                    index=operation_index,
                    detailed=detailed,
                )
            )
        groups.append(
            f"<section class=\"tag\" id=\"tag-{tag_index}\">"
            f"<h2>{_inline(tag_name)}</h2><p>{_inline(tag_descriptions[tag_name])}</p>"
            + "".join(cards)
            + "</section>"
        )

    info = schema.get("info", {})
    title = str(info.get("title", "futureAgent 开放接口"))
    version = str(info.get("version", ""))
    page_title = "完整中文接口目录" if detailed else "中文接口目录"
    current_link = detailed_catalog_url if detailed else compact_catalog_url
    alternate_link = compact_catalog_url if detailed else detailed_catalog_url
    alternate_label = "查看简明目录" if detailed else "查看完整技术目录"
    openapi_href = escape(openapi_url, quote=True)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="futureAgent 中文开放接口目录">
  <title>{escape(title)} · {page_title}</title>
  <style>{_catalog_styles()}</style>
</head>
<body>
  <header class="site-header">
    <p class="eyebrow">futureAgent · 版本 {escape(version)}</p>
    <h1>{escape(title)} · {page_title}</h1>
    <p>由服务端根据当前 OpenAPI 描述生成。接口说明使用中文；技术字段和 JSON Schema 保留原始名称，便于安全联调与自动化。</p>
  </header>
  <main>
    <nav class="toolbar" aria-label="接口目录工具栏">
      <span class="current">当前：{page_title}</span>
      <a href="{escape(alternate_link, quote=True)}">{alternate_label}</a>
      <a class="download" href="{openapi_href}" download="futureagent-openapi.json">下载 OpenAPI JSON</a>
    </nav>
    <section class="intro" aria-labelledby="catalog-introduction">
      <h2 id="catalog-introduction">认证与调用说明</h2>
      {_markdown_description(info.get("description", ""))}
      <p class="notice"><strong>目录范围：</strong>当前共列出 {operation_count} 个接口操作。目录不保存令牌、不代发请求；请在自己的受控客户端中调用接口。</p>
    </section>
    <nav class="tag-nav" aria-label="按功能分组浏览">{nav}</nav>
    {''.join(groups)}
    {_model_catalog(schema, expanded=detailed)}
  </main>
  <footer>futureAgent 中文接口目录 · <a href="{openapi_href}">OpenAPI JSON</a> · <a href="{escape(current_link, quote=True)}">返回当前目录顶部</a></footer>
</body>
</html>"""
