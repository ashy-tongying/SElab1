# -*- coding: utf-8 -*-
"""审计日志。成功写在业务事务里，拒绝写在回滚之后。"""

from __future__ import annotations

from ticketapp.database import Database
from ticketapp.errors import AppError
from ticketapp.models import AuditEntry, format_time
from ticketapp import repo


class AuditService:
    """操作日志服务。对应包图中的审计日志。"""

    def __init__(self, database: Database, clock) -> None:
        self.database = database
        self.clock = clock

    def append(
        self,
        conn,
        actor_id: int,
        action: str,
        target_type: str,
        target_id: int,
        result: str,
        detail: str,
        event_id: int | None,
    ) -> None:
        """在调用方的事务里追加。类图中的「追加」。"""
        repo.insert_audit(
            conn,
            actor_id,
            action,
            target_type,
            target_id,
            result,
            detail,
            event_id,
            format_time(self.clock.now()),
        )

    def append_own(
        self,
        actor_id: int,
        action: str,
        target_type: str,
        target_id: int,
        result: str,
        detail: str,
        event_id: int | None,
    ) -> None:
        """单独提交一条日志，用于已经回滚的拒绝。"""
        with self.database.immediate() as conn:
            self.append(
                conn,
                actor_id,
                action,
                target_type,
                target_id,
                result,
                detail,
                event_id,
            )

    def refuse_update(self) -> None:
        """对外暴露不可修改。"""
        AuditEntry.refuse_mutation()

    def refuse_delete(self) -> None:
        """对外暴露不可删除。"""
        AuditEntry.refuse_mutation()

    def query(
        self,
        actor,
        start: str | None = None,
        end: str | None = None,
        actor_id: int | None = None,
        action: str | None = None,
        event_id: int | None = None,
    ) -> list[AuditEntry]:
        """管理员看全部，组织者看本活动，参与者和检票人员看自己。"""
        clauses = ["1=1"]
        args: list = []
        if actor.role.value == "平台管理员":
            pass
        elif actor.role.value == "组织者":
            clauses.append(
                "event_id IN (SELECT id FROM events WHERE organizer_id=?)"
            )
            args.append(actor.id)
        else:
            if actor_id is not None and actor_id != actor.id:
                raise AppError("无权限查看他人的操作日志")
            clauses.append("actor_id=?")
            args.append(actor.id)
        if start:
            clauses.append("created_at>=?")
            args.append(start)
        if end:
            clauses.append("created_at<=?")
            args.append(end)
        if actor_id is not None and actor.role.value != "参与者":
            if actor.role.value != "检票人员":
                clauses.append("actor_id=?")
                args.append(actor_id)
        if action:
            clauses.append("action=?")
            args.append(action)
        if event_id is not None:
            if actor.role.value == "组织者":
                self._organizer_owns(actor.id, event_id)
            elif actor.role.value not in ("平台管理员",):
                raise AppError("无权限按活动查询日志")
            clauses.append("event_id=?")
            args.append(event_id)
        conn = self.database.connect()
        try:
            return repo.query_audit(conn, " AND ".join(clauses), tuple(args))
        finally:
            conn.close()

    def _organizer_owns(self, organizer_id: int, event_id: int) -> None:
        rows = self.database.read(
            "SELECT organizer_id FROM events WHERE id=?", (event_id,)
        )
        if not rows or rows[0]["organizer_id"] != organizer_id:
            raise AppError("无权限查看该活动的日志")
