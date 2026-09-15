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
        self.policy_path = str(policy_path)
        self.enforcer = casbin.Enforcer(model_path, policy_path)

    def check_permission(
        self, user_role: str, resource: str, action: str
    ) -> None:
        """
        校验权限
        resource 例如: "model:glm-5.3-flash", "skill:coder", "mcp:filesystem"
        action 例如: "use", "read", "write"
        """
        if not self.enforcer.enforce(user_role, resource, action):
            raise HTTPException(
                status_code=403,
                detail=f"权限不足：角色={user_role}，资源={resource}，操作={action}",
            )

    def is_allowed(self, user_role: str, resource: str, action: str) -> bool:
        """无异常地检查权限，便于过滤用户不可见的工具。"""
        return bool(self.enforcer.enforce(user_role, resource, action))

    def add_policy(self, role: str, resource: str, action: str) -> bool:
        """添加权限策略"""
        added = self.enforcer.add_policy(role, resource, action)
        if added:
            self._save_policy_keeping_comments()
        return bool(added)

    def remove_policy(self, role: str, resource: str, action: str) -> bool:
        """移除权限策略"""
        removed = self.enforcer.remove_policy(role, resource, action)
        if removed:
            self._save_policy_keeping_comments()
        return bool(removed)

    def _save_policy_keeping_comments(self) -> None:
        """保存策略，并保住策略文件里的注释。

        casbin 的 ``save_policy()`` 按内存模型整体重写文件，注释与空行都会
        丢——那是运维写给人看的说明（哪条规则为什么存在、user 为什么没有
        dispatch_subagent），一次后台点选就抹掉是不可接受的。
        这里按「规则 → 紧邻其上的注释块」记住归属，重写后原样贴回；
        被删掉的规则连同它的注释一起消失，文件末尾的注释保留在末尾。
        """
        path = Path(self.policy_path)
        stored = path.read_text(encoding="utf-8") if path.exists() else ""
        heads: dict[str, str] = {}
        pending: list[str] = []
        for line in stored.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                pending.append(line.rstrip())
                continue
            if pending:
                heads[stripped] = "\n".join(pending)
            pending = []
        trailing = pending

        self.enforcer.save_policy()

        out: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            head = heads.get(stripped)
            if head:
                out.append(head)
            out.append(stripped)
        out.extend(trailing)
        # 用平台原生换行写回：仓库开启了 autocrlf 且没有 .gitattributes，
        # 在 Windows 上写 LF 会让 git status 一直显示"已修改"（diff 却是空的）。
        path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")

    def get_roles_for_user(self, user: str) -> list[str]:
        """获取用户的所有角色"""
        return self.enforcer.get_roles_for_user(user)

    def get_policies(self) -> list[list[str]]:
        """获取所有策略"""
        return self.enforcer.get_policy()

    def get_roles(self) -> list[str]:
        """获取策略中出现过的角色。"""
        policy_roles = {policy[0] for policy in self.get_policies() if policy}
        inherited_roles = set(self.enforcer.get_all_roles())
        return sorted(policy_roles | inherited_roles)
