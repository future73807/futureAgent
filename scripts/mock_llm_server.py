#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic local stand-in for an OpenAI-compatible LLM endpoint.

Start:
    py scripts/mock_llm_server.py

Listens on http://127.0.0.1:8010 and implements just enough of the OpenAI
HTTP protocol for the futureAgent pipeline to run end to end:

    GET  /v1/models
    POST /v1/chat/completions   (streaming and non-streaming)
    POST /v1/embeddings

Every request is appended to mock_llm.log in the project root.
Standard library only; no external dependencies.
"""

from __future__ import annotations

import datetime
import json
import math
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8010
MODEL_ID = "local-mock"
CREATED_TS = 1700000000

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_ROOT / "mock_llm.log"
_LOG_LOCK = threading.Lock()

SUPERVISOR_MARKER = "执行质量监督者"
PLAN_MARKER = "当前为规划模式"
NEEDS_MORE_MARKER = "NEEDS_MORE"
STOP_CONDITION_PREFIXES = ("目标：", "停止条件：")

VERDICT_MET = '{"met": true, "reason": "本轮产出已满足停止条件。"}'
VERDICT_NOT_MET = '{"met": false, "reason": "还缺一份 README，请补上后再提交。"}'


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------

def log_line(text):
    """Append one line to mock_llm.log. Never raises."""
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    entry = "[%s] %s\n" % (stamp, text)
    with _LOG_LOCK:
        try:
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        except Exception:
            pass


def log_traceback(context):
    with _LOG_LOCK:
        try:
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write("[%s] TRACEBACK %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), context))
                traceback.print_exc(file=fh)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# message helpers (defensive: content may be str, list, None, ...)
# ---------------------------------------------------------------------------

def content_to_text(content):
    """Best-effort flattening of an OpenAI message content field to text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float, bool)):
        return str(content)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if not isinstance(text, str):
                    text = item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return json.dumps(content, ensure_ascii=False)


def get_messages(body):
    messages = body.get("messages")
    if not isinstance(messages, list):
        return []
    return [m for m in messages if isinstance(m, dict)]


def role_of(message):
    role = message.get("role")
    return role if isinstance(role, str) else ""


def system_texts(messages):
    return [content_to_text(m.get("content")) for m in messages if role_of(m) == "system"]


def user_intent(text):
    """从引擎拼装的消息里取出真正的当前请求。

    chat/plan 的请求体是一条 user 消息，里面塞了历史与附件说明，当前请求在
    "Current user request:" 之后。直接拿整段当目标/搜索词会得到一长串前言。
    """
    marker = "Current user request:"
    if marker in text:
        text = text.split(marker, 1)[1]
    return text.strip()


def text_of_last_user(messages):
    for message in reversed(messages):
        if role_of(message) == "user":
            return user_intent(content_to_text(message.get("content")))
    return ""


def text_of_first_user(messages):
    """首条用户消息。

    规划模式的请求可能已经是工具调用后的续跑，最后一条 user 是引擎注入的
    "Continue this conversation using only the tool results"，拿它当计划目标
    会得到一句英文；目标必须取自用户最初那句话。
    """
    for message in messages:
        if role_of(message) == "user":
            text = user_intent(content_to_text(message.get("content")))
            if text.strip():
                return text
    return ""


def text_of_last_tool(messages):
    """Return content of the last tool message, or None if there is none."""
    for message in reversed(messages):
        if role_of(message) == "tool":
            return content_to_text(message.get("content"))
    return None


def has_tool_message(messages):
    return any(role_of(m) == "tool" for m in messages)


def non_empty_tools(body):
    tools = body.get("tools")
    if not isinstance(tools, list):
        return []
    return [t for t in tools if isinstance(t, dict)]


def tool_name_of(tool):
    """OpenAI shape: tools[i].function.name; tolerate tools[i].name."""
    function = tool.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    name = tool.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def pick_tool(tools, hint=""):
    """按用户意图挑一个工具：提到联网/搜索时优先 web_search，否则优先 list_files。"""
    names = [name for name in (tool_name_of(t) for t in tools) if name]
    lowered = (hint or "").lower()
    wants_search = any(
        marker in lowered for marker in ("搜索", "联网", "search", "查一下", "最新")
    )
    preferred = ("web_search",) if wants_search else ("list_files",)
    for candidate in preferred:
        for name in names:
            if name.lower() == candidate:
                return name
    for name in names:
        return name
    return None


# ---------------------------------------------------------------------------
# deterministic reply scripting
# ---------------------------------------------------------------------------

def one_line(text, limit):
    flat = " ".join(str(text).split())
    return flat[:limit]


def split_text_into_chunks(text):
    """Split reply text into 3-6 pieces (best effort, never empty pieces)."""
    if not text:
        return [""]
    size = len(text)
    count = (size + 11) // 12
    count = max(3, min(6, count))
    count = min(count, size)
    if count <= 1:
        return [text]
    base, extra = divmod(size, count)
    pieces = []
    pos = 0
    for index in range(count):
        step = base + (1 if index < extra else 0)
        pieces.append(text[pos:pos + step])
        pos += step
    return pieces


def build_plan_reply(user_text):
    objective = one_line(user_text, 50) or "完成用户提出的任务"
    steps = [
        {
            "title": "读取项目结构",
            "instructions": "查看工作目录下的文件与配置，确认可用的脚本目录、依赖与入口，明确本次任务需要改动的范围。",
        },
        {
            "title": "编写并运行脚本",
            "instructions": "按目标编写 Python 脚本，优先使用标准库实现核心逻辑，在本地运行并检查输出是否符合预期。",
        },
        {
            "title": "汇总结果",
            "instructions": "整理脚本路径、运行命令与关键输出，形成简洁结论反馈给用户。",
        },
    ]
    return json.dumps({"objective": objective, "steps": steps}, ensure_ascii=False)


def default_reply(messages):
    tool_text = text_of_last_tool(messages)
    if tool_text is not None:
        snippet = tool_text[:120].replace("\r", " ").replace("\n", " ")
        return "工具执行完毕，结果摘要：%s；任务已完成。" % snippet
    summary = one_line(text_of_last_user(messages), 20) or "当前请求"
    return "已完成：%s（stand-in 模型 local-mock）" % summary


def decide_reply(body, messages):
    """Decide the scripted reply.

    Returns ("text", reply_text) or ("tool", tool_name, arguments_json).
    Priority: supervisor verdict > plan mode > tool call round > default.
    """
    systems = "\n".join(system_texts(messages))
    last_user = text_of_last_user(messages)

    # 1. SUPERVISOR VERDICT
    if SUPERVISOR_MARKER in systems or last_user.lstrip().startswith(STOP_CONDITION_PREFIXES):
        if NEEDS_MORE_MARKER in last_user:
            return ("text", VERDICT_NOT_MET)
        return ("text", VERDICT_MET)

    # 2. PLAN MODE
    if PLAN_MARKER in systems:
        return ("text", build_plan_reply(text_of_first_user(messages) or last_user))

    # 3. TOOL CALL ROUND (only before any tool result exists)
    tools = non_empty_tools(body)
    if tools and not has_tool_message(messages):
        name = pick_tool(tools, last_user)
        if name:
            if name.lower() == "list_files":
                arguments = '{"path": "."}'
            elif name.lower() == "web_search":
                query = (last_user or "futureAgent").strip()[:80].replace('"', "'")
                arguments = json.dumps({"query": query, "limit": 3}, ensure_ascii=False)
            else:
                arguments = "{}"
            return ("tool", name, arguments)
        log_line("WARN tools present but no tool name parsed; falling back to text reply")

    # 4. DEFAULT
    return ("text", default_reply(messages))


def estimate_usage(messages, reply_text):
    """Arbitrary but non-zero token counts."""
    prompt_chars = sum(len(content_to_text(m.get("content"))) + 8 for m in messages)
    prompt_tokens = max(1, prompt_chars // 4)
    completion_tokens = max(1, len(reply_text or "") // 4)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def embed_vector(text):
    """Deterministic small 1024-dim embedding."""
    seed = sum(ord(ch) for ch in text) % 997 + 1
    return [round(math.sin(seed * 0.013 + index * 0.017) * 0.1, 6) for index in range(1024)]


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class MockLLMHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mock-llm/1.0"

    # keep console quiet; the file log is the source of truth
    def log_message(self, fmt, *args):
        return

    # -- plumbing ----------------------------------------------------------

    def _headers_sent(self):
        return getattr(self, "_sent_headers", False)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8", "replace"))

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._sent_headers = True
        self.wfile.write(body)

    def _send_error_json(self, message, code, status=400):
        if self._headers_sent():
            self.close_connection = True
            return
        try:
            self._send_json(
                {"error": {"message": message, "type": "mock_error", "code": code}},
                status=status,
            )
        except Exception:
            self.close_connection = True

    @staticmethod
    def _route(path):
        clean = path.split("?", 1)[0].rstrip("/") or "/"
        if clean.endswith("/chat/completions"):
            return "chat"
        if clean.endswith("/embeddings"):
            return "embeddings"
        if clean.endswith("/models"):
            return "models"
        return None

    @staticmethod
    def _completion_id():
        return "chatcmpl-mock-%d" % int(time.time() * 1000)

    # -- GET ---------------------------------------------------------------

    def do_GET(self):
        try:
            log_line("GET path=%s" % self.path)
            route = self._route(self.path)
            if route == "models":
                self._send_json({
                    "object": "list",
                    "data": [{
                        "id": MODEL_ID,
                        "object": "model",
                        "created": CREATED_TS,
                        "owned_by": "local",
                    }],
                })
                return
            if self.path.split("?", 1)[0] in ("/", "/health"):
                self._send_json({"status": "ok", "model": MODEL_ID})
                return
            self._send_error_json("not found: %s" % self.path, "not_found", status=404)
        except Exception:
            log_traceback("GET %s" % self.path)
            self._send_error_json("mock server internal error", "internal_error", status=400)

    # -- POST --------------------------------------------------------------

    def do_POST(self):
        path = self.path
        try:
            route = self._route(path)
            body = self._read_json_body()
            if not isinstance(body, dict):
                raise ValueError("request body must be a JSON object")
            if route == "chat":
                self._handle_chat(path, body)
            elif route == "embeddings":
                self._handle_embeddings(path, body)
            else:
                log_line("POST path=%s unrouted method=%s" % (path, body.get("model")))
                self._send_error_json("not found: %s" % path, "not_found", status=404)
        except Exception:
            log_traceback("POST %s" % path)
            self._send_error_json("mock server internal error", "internal_error", status=400)

    # -- chat completions --------------------------------------------------

    def _log_chat_request(self, path, body):
        messages = get_messages(body)
        roles = ",".join(role_of(m) or "?" for m in messages)
        tools = non_empty_tools(body)
        last_text = content_to_text(messages[-1].get("content")) if messages else ""
        preview = last_text[:300].replace("\r", "\\r").replace("\n", "\\n")
        log_line(
            "POST path=%s model=%s stream=%s roles=[%s] tools_present=%s last_message=%s"
            % (
                path,
                body.get("model"),
                bool(body.get("stream")),
                roles,
                bool(tools),
                json.dumps(preview, ensure_ascii=False),
            )
        )

    def _handle_chat(self, path, body):
        self._log_chat_request(path, body)
        model = body.get("model") or MODEL_ID
        messages = get_messages(body)
        stream = bool(body.get("stream"))
        decision = decide_reply(body, messages)
        if decision[0] == "tool":
            _, tool_name, arguments = decision
            if stream:
                self._stream_tool_call(model, tool_name, arguments)
            else:
                self._send_json(self._tool_call_completion(model, messages, tool_name, arguments))
            return
        reply = decision[1]
        if stream:
            self._stream_text(model, reply)
        else:
            self._send_json(self._text_completion(model, messages, reply))

    def _text_completion(self, model, messages, reply):
        return {
            "id": self._completion_id(),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
                "logprobs": None,
            }],
            "usage": estimate_usage(messages, reply),
        }

    def _tool_call_completion(self, model, messages, tool_name, arguments):
        return {
            "id": self._completion_id(),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_mock_1",
                        "type": "function",
                        "function": {"name": tool_name, "arguments": arguments},
                    }],
                },
                "finish_reason": "tool_calls",
                "logprobs": None,
            }],
            "usage": estimate_usage(messages, arguments),
        }

    # -- SSE streaming -----------------------------------------------------

    def _start_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self._sent_headers = True
        self.close_connection = True

    def _write_sse(self, payload):
        line = "data: %s\n\n" % json.dumps(payload, ensure_ascii=False)
        self.wfile.write(line.encode("utf-8"))
        self.wfile.flush()

    def _write_sse_done(self):
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _sse_chunk(self, model, cid, created, delta, finish_reason):
        return {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }

    def _stream_text(self, model, reply):
        cid = self._completion_id()
        created = int(time.time())
        self._start_sse()
        for piece in split_text_into_chunks(reply):
            self._write_sse(self._sse_chunk(model, cid, created, {"content": piece}, None))
        self._write_sse(self._sse_chunk(model, cid, created, {}, "stop"))
        self._write_sse_done()

    def _stream_tool_call(self, model, tool_name, arguments):
        cid = self._completion_id()
        created = int(time.time())
        self._start_sse()
        delta = {
            "tool_calls": [{
                "index": 0,
                "id": "call_mock_1",
                "type": "function",
                "function": {"name": tool_name, "arguments": arguments},
            }]
        }
        self._write_sse(self._sse_chunk(model, cid, created, delta, None))
        self._write_sse(self._sse_chunk(model, cid, created, {}, "tool_calls"))
        self._write_sse_done()

    # -- embeddings --------------------------------------------------------

    def _handle_embeddings(self, path, body):
        model = body.get("model") or "local-embed"
        raw_input = body.get("input")
        if isinstance(raw_input, str):
            inputs = [raw_input]
        elif isinstance(raw_input, list):
            inputs = [
                item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                for item in raw_input
            ]
        elif raw_input is None:
            inputs = [""]
        else:
            inputs = [str(raw_input)]
        log_line("POST path=%s model=%s embeddings=%d" % (path, model, len(inputs)))
        data = [
            {"object": "embedding", "index": index, "embedding": embed_vector(text)}
            for index, text in enumerate(inputs)
        ]
        tokens = max(1, sum(max(1, len(text) // 4) for text in inputs))
        self._send_json({
            "object": "list",
            "data": data,
            "model": model,
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        })


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main():
    server = ThreadingHTTPServer((HOST, PORT), MockLLMHandler)
    server.daemon_threads = True
    print("mock llm listening on 127.0.0.1:8010", flush=True)
    log_line("server start on http://%s:%d" % (HOST, PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
