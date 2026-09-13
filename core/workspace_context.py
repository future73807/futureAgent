"""工作区级上下文：规则、AGENTS.md / CLAUDE.md 与记忆开关。

设置面板里的"规则与记忆"最终要落到每次执行上：规则与仓库约定必须出现在
系统提示里，记忆开关必须真的决定要不要复用历史摘要。这个模块只负责把
工作区偏好翻译成一段可注入的文本与几个布尔开关，拼进 prompt 的动作留在
AgentEngine 里。

工作区文件根（``WORKSPACE_FILES_ROOT``）默认指向本机 MCP 服务的 workspace
目录；Compose 部署下 API 以只读方式挂载同一个卷。读不到就是没有约定文件，
不报错也不阻塞执行——仓库约定属于锦上添花，缺了不该让对话失败。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from config import settings

# 单份约定文件的读取上限。约定是给人看的行为规范，不是数据通道；
# 放大文件进 prompt 只会挤掉真正的上下文预算。
MAX_INSTRUCTION_BYTES = 32_768
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")


def workspace_scope_dir(workspace_id: str) -> Path | None:
    """工作区私有文件目录；根目录不可用时返回 None。

    与 MCP 服务端保持同一套寻址规则：``<root>/.futureagent/workspaces/<sha256>``，
    否则两边的"同一个工作区"会指向不同目录。
    """
    root = str(getattr(settings, "workspace_files_root", "") or "").strip()
    if not root or not workspace_id:
        return None
    scope = Path(root).expanduser() / ".futureagent" / "workspaces" / hashlib.sha256(
        workspace_id.encode("utf-8")
    ).hexdigest()
    return scope


def _read_instruction(scope: Path, name: str) -> str:
    path = scope / name
    try:
        if not path.is_file():
            return ""
        with path.open("rb") as handle:
            raw = handle.read(MAX_INSTRUCTION_BYTES + 1)
    except OSError:
        return ""
    if len(raw) > MAX_INSTRUCTION_BYTES:
        raw = raw[:MAX_INSTRUCTION_BYTES]
    return raw.decode("utf-8", errors="replace").strip()


def load_workspace_instructions(workspace_id: str, preferences: dict | None = None) -> dict[str, str]:
    """按开关读取 AGENTS.md / CLAUDE.md，返回 {文件名: 内容}。"""
    prefs = preferences or {}
    scope = workspace_scope_dir(workspace_id)
    if scope is None:
        return {}
    enabled = {
        "AGENTS.md": bool(prefs.get("include_agents_md", True)),
        "CLAUDE.md": bool(prefs.get("include_claude_md", True)),
    }
    found: dict[str, str] = {}
    for name in INSTRUCTION_FILES:
        if not enabled.get(name, True):
            continue
        content = _read_instruction(scope, name)
        if content:
            found[name] = content
    return found


def build_workspace_context(workspace, preferences: dict | None = None) -> dict:
    """把工作区偏好编译成执行配置里的一段。

    返回的 ``workspace_rules`` 是最终要拼进系统提示的文本（已经在标题里
    标明来源，便于模型区分"硬性规则"与"仓库约定"）；``memory_enabled``
    交给执行层决定是否复用历史摘要。
    """
    prefs = preferences or {}
    sections: list[str] = []
    rules = [str(rule).strip() for rule in (prefs.get("rules") or []) if str(rule).strip()]
    if rules:
        listing = "\n".join(f"{index + 1}. {rule}" for index, rule in enumerate(rules))
        sections.append(f"## 工作区规则（必须遵守）\n{listing}")
    if workspace is not None:
        try:
            agreement = load_workspace_instructions(workspace.id, prefs)
        except Exception:  # pragma: no cover - 读取失败绝不阻塞执行
            agreement = {}
        for name, content in agreement.items():
            sections.append(f"## {name}（仓库约定）\n{content}")
    return {
        "workspace_rules": "\n\n".join(sections),
        "memory_enabled": bool(prefs.get("memory_enabled", True)),
    }


def parse_preferences(raw: str) -> dict:
    """解析工作区偏好的原始 JSON；坏数据按空对象处理。"""
    text = (raw or "").strip()
    if not text or text == "{}":
        return {}
    try:
        payload = json.loads(text)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
