# -*- coding: utf-8 -*-
"""站内通知。只记录，不发送短信或推送。"""

from __future__ import annotations

from ticketapp.database import Database
from ticketapp.errors import AppError
from ticketapp.models import NoticeType, Notification, format_time
from ticketapp import repo


class NotifyService:
    """通知服务。对应包图中的站内通知。"""

    def __init__(self, database: Database, clock) -> None:
        self.database = database
        self.clock = clock

    def add(
        self,
        conn,
        receiver_id: int,
        ntype: NoticeType,
        event_id: int,
        session_id: int | None,
        content: str,
        dedupe_key: str,
    ) -> None:
        """写入一条通知。相同业务键已存在则跳过。"""
        repo.insert_notice(
            conn,
            receiver_id,
            ntype,
            event_id,
            session_id,
            content,
            format_time(self.clock.now()),
            dedupe_key,
        )

    def list_mine(self, actor) -> list[Notification]:
        """接收人查看自己的通知。"""
        conn = self.database.connect()
        try:
            return repo.list_notices(conn, actor.id)
        finally:
            conn.close()

    def mark_read(self, actor, notice_id: int) -> Notification:
        """标记已读。不能改别人的通知。"""
        with self.database.immediate() as conn:
            notice = repo.get_notice(conn, notice_id)
            if notice.receiver_id != actor.id and actor.role.value != "平台管理员":
                raise AppError("无权限")
            notice.mark_read(format_time(self.clock.now()))
            repo.save_notice(conn, notice)
            return notice
