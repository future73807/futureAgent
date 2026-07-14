"""
AuthManager - 基于 PyCasbin 的权限管理
开源轮子: https://github.com/casbin/pycasbin
"""
from pathlib import Path

import casbin
from fastapi import HTTPException

from config import settings


class AuthManager:
    def __init__(
        self,
        model_path: str = None,
        policy_path: str = None,
    ):
        model_path = model_path or settings.casbin_model_path
        policy_path = policy_path or settings.casbin_policy_path
        # 确保目录存在
        Path(model_path).parent.mkdir(parents=True, exist_ok=True)
        Path(policy_path).parent.mkdir(parents=True, exist_ok=True)
        self.enforcer = casbin.Enforcer(model_path, policy_path)

    def check_permission(
        self, user_role: str, resource: str, action: str
    ):
        """
        校验权限
        resource 例如: "model:gpt-4o", "skill:coder", "mcp:filesystem"
        action 例如: "use", "read", "write"
        """
        if not self.enforcer.enforce(user_role, resource, action):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: role={user_role}, resource={resource}, action={action}",
            )

    def add_policy(self, role: str, resource: str, action: str):
        """添加权限策略"""
        self.enforcer.add_policy(role, resource, action)

    def remove_policy(self, role: str, resource: str, action: str):
        """移除权限策略"""
        self.enforcer.remove_policy(role, resource, action)

    def get_roles_for_user(self, user: str) -> list[str]:
        """获取用户的所有角色"""
        return self.enforcer.get_roles_for_user(user)

    def get_policies(self) -> list[list[str]]:
        """获取所有策略"""
        return self.enforcer.get_policy()
