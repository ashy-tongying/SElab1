# -*- coding: utf-8 -*-
"""按场次统计，并导出脱敏名单。"""

from __future__ import annotations

import csv
import io

from ticketapp.database import Database
from ticketapp.errors import AppError
from ticketapp.models import Role, mask_phone
from ticketapp import repo


class StatsService:
    """统计与导出。对应包图中的统计与导出。"""

    def __init__(self, database: Database, audit) -> None:
        self.database = database
        self.audit = audit

    def summary_text(self, actor, event_id: int) -> str:
        """组织者或管理员查看的文字统计。"""
        data = self.summary(actor, event_id)
        lines = [f"活动：{data['title']}（{data['status']}）"]
        if not data["sessions"]:
            lines.append("暂无场次")
            return "\n".join(lines)
        for item in data["sessions"]:
            rate = f"{item['rate']:.0%}"
            lines.append(
                f"{item['name']}｜容量 {item['capacity']}｜已报名 {item['enrolled']}"
                f"｜剩余 {item['remaining']}｜候补 {item['waitlist']}"
                f"｜签到 {item['checked']}｜签到率 {rate}"
            )
            for name, count in item["tickets"]:
                lines.append(f"    票种 {name}：{count} 人")
        return "\n".join(lines)

    def summary(self, actor, event_id: int) -> dict:
        """按场次汇总人数。签到率分母为已通过、已签到和已缺席。"""
        conn = self.database.connect()
        try:
            event = repo.get_event(conn, event_id)
            self._allow(conn, actor, event, export=False)
            sessions = []
            for session in repo.sessions_of(conn, event.id):
                checked = repo.count_status(conn, session.id, "已签到")
                approved = repo.count_status(conn, session.id, "已通过")
                absent = repo.count_status(conn, session.id, "已缺席")
                base = checked + approved + absent
                tickets = [
                    (row["name"], int(row["n"]))
                    for row in repo.count_by_ticket(conn, session.id)
                ]
                sessions.append({
                    "name": session.name,
                    "capacity": session.capacity,
                    "enrolled": session.enrolled,
                    "waitlist": session.waitlist,
                    "remaining": session.remaining(),
                    "checked": checked,
                    "rate": (checked / base) if base else 0,
                    "tickets": tickets,
                })
            return {
                "title": event.title,
                "status": event.status.value,
                "sessions": sessions,
            }
        finally:
            conn.close()

    def roster(self, actor, event_id: int) -> list[dict]:
        """报名名单。手机号脱敏。检票人员可查看，不能导出。"""
        conn = self.database.connect()
        try:
            event = repo.get_event(conn, event_id)
            self._allow(conn, actor, event, export=False)
            return [_public_row(row) for row in repo.roster_rows(conn, event_id)]
        finally:
            conn.close()

    def export_csv(self, actor, event_id: int, confirmed: bool) -> str:
        """导出名单并记日志。检票人员会被拒绝。"""
        if actor.role == Role.CHECKER:
            raise AppError("检票人员不能导出名单")
        if not confirmed:
            raise AppError("导出名单需要二次确认")
        with self.database.immediate() as conn:
            event = repo.get_event(conn, event_id)
            if not actor.can_execute("export", event.organizer_id):
                raise AppError("无权限")
            rows = [_public_row(row) for row in repo.roster_rows(conn, event_id)]
            self.audit.append(
                conn, actor.id, "名单导出", "活动", event.id, "成功",
                f"共 {len(rows)} 条", event.id,
            )
        return _to_csv(rows)

    def _allow(self, conn, actor, event, export: bool) -> None:
        if export:
            return
        if actor.can_execute("view_roster", event.organizer_id):
            return
        grant = repo.find_grant(conn, event.id, actor.id)
        if grant is not None and grant.covers(event.id):
            return
        raise AppError("无权限")


def _public_row(row) -> dict:
    signed = "已签到" if row["status"] == "已签到" else "未签到"
    return {
        "username": row["username"],
        "phone": mask_phone(row["phone"]),
        "session": row["session_name"],
        "ticket": row["ticket_name"],
        "status": row["status"],
        "created_at": row["created_at"],
        "signed": signed,
        "code": row["code"],
        "payment": row["payment_status"] or "",
        "id": row["id"],
    }


def _to_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["用户名", "手机号", "场次", "票种", "报名状态", "报名时间", "签到状态"])
    for row in rows:
        writer.writerow([
            row["username"], row["phone"], row["session"], row["ticket"],
            row["status"], row["created_at"], row["signed"],
        ])
    return buffer.getvalue()
