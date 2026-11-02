# -*- coding: utf-8 -*-
"""签到核销。重复签到不新增第二条签到记录。"""

from __future__ import annotations

from ticketapp.database import Database
from ticketapp.errors import AppError, RuleBreak
from ticketapp.models import EventStatus, RegStatus, format_time, parse_time
from ticketapp import repo


class CheckinService:
    """签到核销。对应包图中的签到核销。"""

    def __init__(self, database: Database, audit, clock) -> None:
        self.database = database
        self.audit = audit
        self.clock = clock

    def redeem(self, actor, code: str) -> dict:
        """扫码或输入报名号。没有本活动授权则拒绝。"""
        found = self._load(actor, code)
        record = found["reg"]
        event = found["event"]
        session = found["session"]
        if found["grant"] is None or not found["grant"].covers(event.id):
            self.audit.append_own(
                actor.id, "签到", "报名记录", record.id, "拒绝",
                "不是本活动检票人员", event.id,
            )
            raise AppError("无权限，您不是本活动的检票人员")
        if record.status == RegStatus.CHECKED_IN:
            self.audit.append_own(
                actor.id, "重复签到", "报名记录", record.id, "拒绝", "已签到", event.id
            )
            raise AppError("已签到，不能重复核销")
        if record.status != RegStatus.APPROVED:
            self.audit.append_own(
                actor.id, "签到", "报名记录", record.id, "拒绝",
                record.status.value, event.id,
            )
            raise AppError(f"当前状态为{record.status.value}，不能签到")
        if event.status == EventStatus.CANCELLED:
            raise AppError("活动已取消，不能签到")
        if self.clock.now() >= parse_time(session.end_at):
            raise AppError("场次已结束，不能签到")
        saved = None
        try:
            with self.database.immediate() as conn:
                current = repo.get_reg(conn, record.id)
                if current.status == RegStatus.CHECKED_IN:
                    raise RuleBreak("已签到")
                if current.status != RegStatus.APPROVED:
                    raise AppError(f"当前状态为{current.status.value}，不能签到")
                current.transition_to(RegStatus.CHECKED_IN)
                repo.save_reg(conn, current)
                saved = repo.insert_checkin(
                    conn, current.id, actor.id, format_time(self.clock.now())
                )
                self.audit.append(
                    conn, actor.id, "签到", "报名记录", current.id, "成功",
                    found["user"].username, event.id,
                )
        except RuleBreak as exc:
            self.audit.append_own(
                actor.id, "重复签到", "报名记录", record.id, "拒绝", exc.message, event.id
            )
            raise AppError("已签到，不能重复核销") from exc
        return {
            "username": found["user"].username,
            "ticket": found["ticket"].name,
            "code": record.code,
            "event": event.title,
            "session": session.name,
            "checked_at": saved.checked_at,
        }

    def granted_events(self, actor) -> list:
        """当前用户可以核销的活动。"""
        conn = self.database.connect()
        try:
            grants = repo.grants_of_user(conn, actor.id)
            return [repo.get_event(conn, grant.event_id) for grant in grants]
        finally:
            conn.close()

    def _load(self, actor, code: str) -> dict:
        conn = self.database.connect()
        try:
            record = repo.get_reg_by_code(conn, code.strip())
            if record is None:
                raise AppError("报名号不存在")
            session = repo.get_session(conn, record.session_id)
            event = repo.get_event(conn, session.event_id)
            ticket = repo.get_ticket(conn, record.ticket_id)
            user = repo.get_user(conn, record.user_id)
            grant = repo.find_grant(conn, event.id, actor.id)
            return {
                "reg": record,
                "session": session,
                "event": event,
                "ticket": ticket,
                "user": user,
                "grant": grant,
            }
        finally:
            conn.close()
