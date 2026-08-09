"""Regression checks for the Chinese API documentation contract."""

from __future__ import annotations

import asyncio
import json
import unittest

from starlette.requests import Request

from api.docs_catalog import render_api_catalog
from main import app, api_documentation_catalog, complete_api_documentation_catalog


class ChineseOpenApiDocumentationTests(unittest.TestCase):
    @staticmethod
    def _request(path: str) -> Request:
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
                "root_path": "",
            }
        )

    def test_openapi_schema_has_chinese_guidance_for_every_operation(self):
        schema = app.openapi()

        self.assertEqual(schema["info"]["title"], "futureAgent 开放接口")
        self.assertIn("X-Workspace-ID", schema["info"]["description"])
        self.assertEqual(schema["paths"]["/api/v1/auth/login"]["post"]["summary"], "登录")
        self.assertEqual(
            schema["paths"]["/api/v1/tasks/{task_id}/execute"]["post"]["summary"],
            "执行已审批的工作计划",
        )
        self.assertEqual(
            schema["paths"]["/api/v1/models/{model_id}/probe"]["post"]["summary"],
            "探测模型可用性",
        )
        self.assertEqual(
            schema["paths"]["/api/v1/chat/agent"]["post"]["summary"],
            "发送智能助手聊天请求",
        )
        self.assertIn("工作模式", schema["tags"][4]["description"])
        self.assertIn("服务端从本 OpenAPI 描述生成中文接口目录", schema["info"]["description"])
        self.assertIn("不加载第三方", schema["info"]["description"])
        documentation_text = json.dumps(schema, ensure_ascii=False)
        self.assertNotIn("Work 模式", documentation_text)
        self.assertNotIn("Agent 聊天", documentation_text)
        for path_item in schema["paths"].values():
            for method, operation in path_item.items():
                if method in {"get", "post", "put", "patch", "delete"}:
                    self.assertNotEqual(operation["summary"], "接口操作")

        bearer_schemes = [
            scheme
            for scheme in schema["components"]["securitySchemes"].values()
            if scheme.get("type") == "http" and scheme.get("scheme") == "bearer"
        ]
        self.assertTrue(bearer_schemes)
        self.assertIn("access_token", bearer_schemes[0]["description"])

    def test_documentation_entries_render_complete_chinese_catalog_without_third_party_ui(self):
        catalog = asyncio.run(api_documentation_catalog(self._request("/docs")))
        detailed_catalog = asyncio.run(complete_api_documentation_catalog(self._request("/redoc")))
        schema = app.openapi()

        for response in (catalog, detailed_catalog):
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'lang="zh-CN"', response.body)
            self.assertIn(b"/openapi.json", response.body)
            self.assertEqual(response.headers["content-language"], "zh-CN")
            self.assertIn("default-src 'none'".encode(), response.headers["content-security-policy"].encode())
            self.assertNotIn(b"SwaggerUIBundle", response.body)
            self.assertNotIn(b"swagger-ui", response.body.lower())
            self.assertNotIn(b"cdn.jsdelivr.net", response.body)

        self.assertIn("中文接口目录".encode(), catalog.body)
        self.assertIn("完整中文接口目录".encode(), detailed_catalog.body)
        self.assertIn("下载 OpenAPI JSON".encode(), catalog.body)
        self.assertIn("认证与调用说明".encode(), catalog.body)
        self.assertIn("账户与会话".encode(), catalog.body)
        self.assertIn("登录".encode(), catalog.body)
        self.assertIn("发送智能助手聊天请求".encode(), catalog.body)
        self.assertIn(b"RegisterRequest", detailed_catalog.body)
        for path in schema["paths"]:
            self.assertIn(path.encode(), catalog.body)

        public_route_paths = {
            route.path for route in app.routes if hasattr(route, "path")
        }
        self.assertTrue({"/docs", "/redoc"}.issubset(public_route_paths))
        self.assertNotIn("/docs/oauth2-redirect", public_route_paths)

        operation_count = sum(
            1
            for path_item in schema["paths"].values()
            for method in path_item
            if method in {"get", "post", "put", "patch", "delete", "head", "options"}
        )
        self.assertIn(f"当前共列出 {operation_count} 个接口操作".encode(), catalog.body)

    def test_catalog_escapes_openapi_text_and_has_no_runtime_script(self):
        schema = {
            "info": {"title": "<危险标题>", "version": "测试", "description": "<script>不应执行</script>"},
            "tags": [{"name": "<危险分组>", "description": "说明"}],
            "paths": {
                "/api/test": {
                    "get": {
                        "summary": "<危险摘要>",
                        "description": "<img src=x onerror=alert(1)>",
                        "tags": ["<危险分组>"],
                        "responses": {"200": {"description": "请求成功"}},
                    }
                }
            },
            "components": {"schemas": {}, "securitySchemes": {}},
        }

        page = render_api_catalog(
            schema,
            openapi_url="/openapi.json",
            compact_catalog_url="/docs",
            detailed_catalog_url="/redoc",
            detailed=False,
        )
        self.assertIn("&lt;危险标题&gt;", page)
        self.assertIn("&lt;script&gt;不应执行&lt;/script&gt;", page)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("<img src=x", page)


if __name__ == "__main__":
    unittest.main()
