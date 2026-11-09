# -*- coding: utf-8 -*-
"""用户、登录和检票授权。"""

from __future__ import annotations

import re

from ticketapp.database import Database
from ticketapp.errors import AppError
from ticketapp.models import CheckinGrant, Role, User, digest_password, format_time
from ticketapp import repo

_PHONE = re.compile(r"^1\d{10}$")
_NAME = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{2,20}$")


class UserService:
    """用户与权限。对应包图中的用户与权限。"""

    def __init__(self, database: Database, audit, clock) -> None:
        self.database = database
        self.audit = audit
        self.clock = clock

    def ensure_admin(self, username: str, phone: str, password: str) -> None:
        """空库时放入管理员，避免没有人能登录。"""
        conn = self.database.connect()
        try:
            if repo.get_user_by_name(conn, username):
                return
            repo.insert_user(
                conn, username, phone, digest_password(password), Role.ADMIN
            )
            conn.commit()
        finally:
            conn.close()

    def login(self, username: str, password: str) -> User:
        """登录。未登录不能进入后续功能。"""
        conn = self.database.connect()
        try:
            user = repo.get_user_by_name(conn, username.strip())
        finally:
            conn.close()
        if user is None or not user.enabled or not user.verify(password):
            raise AppError("用户名或密码错误，或账号已停用")
        return user

    def create_user(
        self,
        actor: User,
        username: str,
        phone: str,
        password: str,
        role: Role,
    ) -> User:
        """管理员开户。"""
        if not actor.can_execute("manage_users"):
            raise AppError("无权限")
        self._check_profile(username, phone, password)
        with self.database.immediate() as conn:
            user = repo.insert_user(
                conn, username.strip(), phone.strip(), digest_password(password), role
            )
            self.audit.append(
                conn, actor.id, "权限变更", "用户", user.id, "成功",
                f"创建账号 {user.username}，角色 {role.value}", None,
            )
            return user

    def set_enabled(self, actor: User, user_id: int, enabled: bool, confirmed: bool) -> User:
        """停用或启用。停用需要二次确认，不能停用自己。"""
        if not actor.can_execute("manage_users"):
            raise AppError("无权限")
        if not confirmed:
            raise AppError("变更账号状态需要二次确认")
        if actor.id == user_id and not enabled:
            raise AppError("不能停用自己")
        with self.database.immediate() as conn:
            user = repo.get_user(conn, user_id)
            if user.role == Role.ADMIN and not enabled:
                admins = [
                    item for item in repo.list_users(conn)
                    if item.role == Role.ADMIN and item.enabled and item.id != user.id
                ]
                if not admins:
                    raise AppError("至少保留一名启用的管理员")
            user.enabled = enabled
            repo.save_user_flags(conn, user)
            word = "启用" if enabled else "停用"
            self.audit.append(
                conn, actor.id, "权限变更", "用户", user.id, "成功",
                f"{word}账号 {user.username}", None,
            )
            return user

    def set_role(self, actor: User, user_id: int, role: Role, confirmed: bool) -> User:
        """调整角色，记入权限变更日志。"""
        if not actor.can_execute("manage_users"):
            raise AppError("无权限")
        if not confirmed:
            raise AppError("调整角色需要二次确认")
        if actor.id == user_id:
            raise AppError("不能修改自己的角色")
        with self.database.immediate() as conn:
            user = repo.get_user(conn, user_id)
            previous = user.role.value
            user.role = role
            repo.save_user_flags(conn, user)
            self.audit.append(
                conn, actor.id, "权限变更", "用户", user.id, "成功",
                f"{user.username} 的角色从 {previous} 改为 {role.value}", None,
            )
            return user

    def list_users(self, actor: User) -> list[User]:
        """用户管理列表。"""
        if not actor.can_execute("manage_users"):
            raise AppError("无权限")
        conn = self.database.connect()
        try:
            return repo.list_users(conn)
        finally:
            conn.close()

    def grant_checker(self, actor: User, event_id: int, user_id: int) -> CheckinGrant:
        """组织者指定本活动检票人员，也可以授给参与者账号。"""
        with self.database.immediate() as conn:
            event = repo.get_event(conn, event_id)
            if not actor.can_execute("grant_checker", event.organizer_id):
                raise AppError("无权限")
            target = repo.get_user(conn, user_id)
            if not target.enabled:
                raise AppError("不能授权给已停用的账号")
            grant = repo.insert_grant(
                conn, event_id, user_id, actor.id, format_time(self.clock.now())
            )
            self.audit.append(
                conn, actor.id, "检票授权", "活动", event_id, "成功",
                f"授权 {target.username} 核销本活动", event_id,
            )
            return grant

    def my_grants(self, actor: User) -> list[CheckinGrant]:
        """当前用户拿到的检票授权。"""
        conn = self.database.connect()
        try:
            return repo.grants_of_user(conn, actor.id)
        finally:
            conn.close()

    def covers_event(self, actor: User, event_id: int) -> bool:
        """活动检票授权是否覆盖该活动。"""
        conn = self.database.connect()
        try:
            grant = repo.find_grant(conn, event_id, actor.id)
        finally:
            conn.close()
        return grant is not None and grant.covers(event_id)

    @staticmethod
    def _check_profile(username: str, phone: str, password: str) -> None:
        if not _NAME.match(username.strip()):
            raise AppError("用户名需为 2 到 20 位字母、数字、下划线或汉字")
        if not _PHONE.match(phone.strip()):
            raise AppError("手机号应为 11 位且以 1 开头")
        if len(password) < 6:
            raise AppError("密码至少 6 位")
