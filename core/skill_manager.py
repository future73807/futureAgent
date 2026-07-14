"""
SkillManager - Skill 装配器
Skill = 特定领域的提示词模板 + 专属工具集 + 专属子图
"""
from typing import Optional

from pydantic import BaseModel
from langchain_core.tools import StructuredTool


class Skill(BaseModel):
    name: str
    description: str
    system_prompt: str
    allowed_tool_names: list[str] = []  # 该 Skill 允许调用的工具白名单


class SkillManager:
    def __init__(self):
        self.skills_db: dict[str, Skill] = {}

    def register_skill(self, skill: Skill):
        """注册一个 Skill"""
        self.skills_db[skill.name] = skill

    def get_skill(self, skill_name: str) -> Optional[Skill]:
        """获取 Skill 配置"""
        return self.skills_db.get(skill_name)

    def list_skills(self) -> list[Skill]:
        """列出所有已注册的 Skill"""
        return list(self.skills_db.values())

    def assemble_skill(
        self, skill_name: str, available_tools: list[StructuredTool]
    ) -> dict:
        """
        装配 Skill，过滤出可用的工具
        返回: {"system_prompt": str, "tools": list[StructuredTool]}
        """
        skill = self.skills_db.get(skill_name)
        if not skill:
            raise ValueError(f"Skill '{skill_name}' not found")

        # 如果没有配置白名单，则允许使用所有工具
        if not skill.allowed_tool_names:
            return {
                "system_prompt": skill.system_prompt,
                "tools": available_tools,
            }

        # 根据白名单过滤工具
        active_tools = [
            tool
            for tool in available_tools
            if tool.name in skill.allowed_tool_names
        ]
        return {
            "system_prompt": skill.system_prompt,
            "tools": active_tools,
        }
