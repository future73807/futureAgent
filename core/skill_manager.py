"""Skill 定义的加载、持久化与装配。"""
from pathlib import Path
from typing import Optional

import yaml
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from config import settings


class Skill(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{1,63}$")
    description: str = Field(min_length=1, max_length=500)
    system_prompt: str = Field(min_length=1)
    allowed_tool_names: list[str] = Field(default_factory=list)


class SkillManager:
    def __init__(self, skills_dir: str | Path | None = None):
        self.skills_dir = Path(skills_dir or settings.skills_dir).resolve()
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skills_db: dict[str, Skill] = {}
        self.register_skill(Skill(
            name="default",
            description="默认助手",
            system_prompt="你是一个有用、可靠的助手。请清晰、准确地回答用户问题。",
        ))
        self.load_skills()

    def load_skills(self) -> None:
        """从 skills 目录加载全部 YAML，文件内容是唯一数据源。"""
        for path in sorted(self.skills_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("顶层必须是对象")
                self.register_skill(Skill.model_validate(data))
            except Exception as exc:
                raise ValueError(f"无法加载 Skill 文件 {path.name}: {exc}") from exc

    def register_skill(self, skill: Skill) -> Skill:
        """注册一个 Skill"""
        self.skills_db[skill.name] = skill
        return skill

    def save_skill(self, skill: Skill, *, overwrite: bool = False) -> Skill:
        """写入 YAML 并注册 Skill。"""
        path = self._skill_path(skill.name)
        if path.exists() and not overwrite:
            raise FileExistsError(f"Skill '{skill.name}' already exists")
        path.write_text(
            yaml.safe_dump(
                skill.model_dump(),
                allow_unicode=True,
                sort_keys=False,
                width=100,
            ),
            encoding="utf-8",
        )
        return self.register_skill(skill)

    def delete_skill(self, skill_name: str) -> bool:
        """删除持久化 Skill；内置 default 不允许删除。"""
        if skill_name == "default":
            raise ValueError("内置 default Skill 不能删除")
        if skill_name not in self.skills_db:
            return False
        path = self._skill_path(skill_name)
        if path.exists():
            path.unlink()
        self.skills_db.pop(skill_name, None)
        return True

    def _skill_path(self, skill_name: str) -> Path:
        # Skill.name 已有限制；这里再次校验，确保任何调用路径都不能越界。
        valid_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        if (
            len(skill_name) < 2
            or len(skill_name) > 64
            or not skill_name[0].isalpha()
            or any(char not in valid_chars for char in skill_name)
        ):
            raise ValueError("非法的 Skill 名称")
        path = (self.skills_dir / f"{skill_name}.yaml").resolve()
        if path.parent != self.skills_dir:
            raise ValueError("非法的 Skill 路径")
        return path

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
