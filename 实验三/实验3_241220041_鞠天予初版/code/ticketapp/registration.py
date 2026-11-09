# -*- coding: utf-8 -*-
"""报名、取消、审核、候补递补。名额只在本包的事务里修改。"""

from __future__ import annotations

from typing import NoReturn

from ticketapp.database import Database
from ticketapp.errors import AppError, RuleBreak
from ticketapp.models import (
    EventStatus,
    NoticeType,
    PayStatus,
    RegStatus,
    format_time,
    parse_time,
)
from ticketapp import repo


class RegistrationService:
    """报名与候补。对应包图中的报名与候补。"""

    def __init__(self, database: Database, audit, notify, clock) -> None:
        self.database = database
        self.audit = audit
        self.notify = notify
        self.clock = clock

    def register(self, actor, session_id: int, ticket_id: int):
        """提交报名。事务内重新读取场次，不用页面上的旧余量。"""
        if not actor.can_execute("register"):
            raise AppError("只有参与者可以报名")
        preview = self._preview(session_id, ticket_id)
        closed = self._closed_reason(preview["event"], preview["session"])
        if closed:
            self._reject(actor, "报名", "场次", session_id, preview["event"].id, closed)
        try:
            with self.database.immediate() as conn:
                event = repo.get_event(conn, preview["event"].id)
                session = repo.get_session(conn, session_id)
                ticket = repo.get_ticket(conn, ticket_id)
                if ticket.session_id != session.id:
                    raise RuleBreak("票种不属于该场次")
                closed_now = self._closed_reason(event, session)
                if closed_now:
                    raise RuleBreak(closed_now)
                if repo.active_reg(conn, actor.id, session.id):
                    raise RuleBreak("您已报名该场次")
                created = format_time(self.clock.now())
                if event.need_review:
                    record = repo.insert_reg(
                        conn, actor.id, session.id, ticket.id,
                        RegStatus.PENDING, None, None, created,
                    )
                    self.audit.append(
                        conn, actor.id, "报名", "报名记录", record.id,
                        "成功", "待审核", event.id,
                    )
                    return record
                if session.has_seat():
                    session.occupy()
                    payment = None if ticket.is_free else PayStatus.UNPAID
                    record = repo.insert_reg(
                        conn, actor.id, session.id, ticket.id,
                        RegStatus.APPROVED, payment, None, created,
                    )
                    repo.save_session(conn, session)
                    self.audit.append(
                        conn, actor.id, "报名", "报名记录", record.id,
                        "成功", "已通过", event.id,
                    )
                    return record
                session.enter_waitlist()
                record = repo.insert_reg(
                    conn, actor.id, session.id, ticket.id,
                    RegStatus.WAITLIST, None, created, created,
                )
                repo.save_session(conn, session)
                self.audit.append(
                    conn, actor.id, "报名", "报名记录", record.id,
                    "成功", "候补中", event.id,
                )
                return record
        except RuleBreak as exc:
            self._reject(actor, "报名", "场次", session_id, preview["event"].id, exc.message)

    def cancel(self, actor, reg_id: int):
        """参与者在截止前取消。已通过的名额会自动递补最早的候补。"""
        if not actor.can_execute("cancel_own"):
            raise AppError("无权限")
        event_id = self._event_id_of_reg(reg_id)
        try:
            with self.database.immediate() as conn:
                record = repo.get_reg(conn, reg_id)
                if record.user_id != actor.id:
                    raise AppError("只能取消自己的报名")
                session = repo.get_session(conn, record.session_id)
                event = repo.get_event(conn, session.event_id)
                if self.clock.now() > parse_time(session.deadline):
                    raise RuleBreak("报名已截止，不能取消")
                if record.status in (
                    RegStatus.CHECKED_IN,
                    RegStatus.INVALID,
                    RegStatus.ABSENT,
                    RegStatus.CANCELLED,
                ):
                    raise RuleBreak(f"当前状态为{record.status.value}，不能取消")
                if record.status == RegStatus.PENDING:
                    record.transition_to(RegStatus.CANCELLED)
                    record.reason = "用户取消"
                    repo.save_reg(conn, record)
                    self._log_cancel(conn, actor, record, event.id)
                    return record
                if record.status == RegStatus.WAITLIST:
                    record.transition_to(RegStatus.CANCELLED)
                    record.reason = "用户取消"
                    session.leave_waitlist()
                    repo.save_reg(conn, record)
                    repo.save_session(conn, session)
                    self._log_cancel(conn, actor, record, event.id)
                    return record
                record.transition_to(RegStatus.CANCELLED)
                record.reason = "用户取消"
                session.release()
                repo.save_reg(conn, record)
                promoted = self._promote_earliest(conn, session, event)
                repo.save_session(conn, session)
                self._log_cancel(conn, actor, record, event.id)
                if promoted is not None:
                    self.audit.append(
                        conn, actor.id, "递补", "报名记录", promoted.id,
                        "成功", "自动递补", event.id,
                    )
                return record
        except RuleBreak as exc:
            self._reject(actor, "取消报名", "报名记录", reg_id, event_id, exc.message)

    def review(self, actor, reg_id: int, accept: bool, reason: str = ""):
        """组织者审核报名。满员时通过会转入候补，避免超卖。"""
        with self.database.immediate() as conn:
            record = repo.get_reg(conn, reg_id)
            session = repo.get_session(conn, record.session_id)
            event = repo.get_event(conn, session.event_id)
            if not actor.can_execute("review_reg", event.organizer_id):
                raise AppError("无权限")
            if record.status != RegStatus.PENDING:
                raise AppError("只能审核待审核的报名")
            if not accept:
                if not reason.strip():
                    raise AppError("拒绝必须填写原因")
                record.transition_to(RegStatus.CANCELLED)
                record.reason = reason.strip()
                repo.save_reg(conn, record)
                self._review_notice(conn, record, event, session.id, False)
                self.audit.append(
                    conn, actor.id, "报名", "报名记录", record.id,
                    "拒绝", reason.strip(), event.id,
                )
                return record
            ticket = repo.get_ticket(conn, record.ticket_id)
            if session.has_seat():
                record.transition_to(RegStatus.APPROVED)
                session.occupy()
                if not ticket.is_free:
                    record.payment = PayStatus.UNPAID
                detail = "审核通过"
            else:
                record.transition_to(RegStatus.WAITLIST)
                session.enter_waitlist()
                record.waitlist_at = format_time(self.clock.now())
                detail = "审核时已满，转入候补"
            repo.save_session(conn, session)
            repo.save_reg(conn, record)
            self._review_notice(conn, record, event, session.id, accept)
            self.audit.append(
                conn, actor.id, "报名", "报名记录", record.id,
                "成功", detail, event.id,
            )
            return record

    def promote_manual(self, actor, reg_id: int):
        """手动递补。有更早的候补时拒绝，自动递补优先。"""
        with self.database.immediate() as conn:
            record = repo.get_reg(conn, reg_id)
            session = repo.get_session(conn, record.session_id)
            event = repo.get_event(conn, session.event_id)
            if not actor.can_execute("review_reg", event.organizer_id):
                raise AppError("无权限")
            if record.status != RegStatus.WAITLIST:
                raise AppError("只能递补候补中的报名")
            earliest = repo.earliest_wait(conn, session.id)
            if earliest is None or earliest.id != record.id:
                raise AppError("自动递补优先，请先递补更早进入候补的用户")
            if not session.has_seat():
                raise AppError("没有剩余名额，不能递补")
            promoted = self._promote_earliest(conn, session, event)
            repo.save_session(conn, session)
            self.audit.append(
                conn, actor.id, "递补", "报名记录", promoted.id,
                "成功", "手动递补", event.id,
            )
            return promoted

    def mark_paid(self, actor, reg_id: int, confirmed: bool):
        """组织者或管理员手动标记收费票已支付。"""
        if not confirmed:
            raise AppError("标记支付需要二次确认")
        with self.database.immediate() as conn:
            record = repo.get_reg(conn, reg_id)
            session = repo.get_session(conn, record.session_id)
            event = repo.get_event(conn, session.event_id)
            if not actor.can_execute("mark_payment", event.organizer_id):
                raise AppError("无权限")
            if record.status not in (
                RegStatus.APPROVED, RegStatus.CHECKED_IN, RegStatus.ABSENT
            ):
                raise AppError("当前报名不能标记支付")
            before = record.payment.value if record.payment else "无"
            record.mark_payment(PayStatus.PAID)
            repo.save_reg(conn, record)
            self.audit.append(
                conn, actor.id, "支付标记", "报名记录", record.id, "成功",
                f"{before}改为{record.payment.value}", event.id,
            )
            return record

    def list_mine(self, actor) -> list[dict]:
        """参与者查看自己的报名。"""
        if not actor.can_execute("view_self"):
            raise AppError("无权限")
        conn = self.database.connect()
        try:
            return [dict(row) for row in repo.regs_of_user(conn, actor.id)]
        finally:
            conn.close()

    def invalidate_event(self, conn, event) -> None:
        """活动取消：有效报名改为已失效，候补清空，收费票标记待退款。

        已签到保留。状态图里活动取消走「已失效」，不是参与者主动取消。
        """
        sessions = repo.sessions_of(conn, event.id)
        receivers: set[int] = set()
        for session in sessions:
            for record in repo.regs_of_session(conn, session.id):
                if record.status == RegStatus.CHECKED_IN:
                    receivers.add(record.user_id)
                    continue
                if record.status == RegStatus.APPROVED:
                    record.transition_to(RegStatus.INVALID)
                    session.release()
                elif record.status == RegStatus.WAITLIST:
                    record.transition_to(RegStatus.INVALID)
                    session.leave_waitlist()
                elif record.status == RegStatus.PENDING:
                    record.transition_to(RegStatus.INVALID)
                else:
                    continue
                record.mark_refund_if_charged()
                receivers.add(record.user_id)
                repo.save_reg(conn, record)
            repo.save_session(conn, session)
        for user_id in receivers:
            self.notify.add(
                conn, user_id, NoticeType.CANCELLED, event.id, None,
                f"活动「{event.title}」已取消",
                f"cancel:{event.id}:{user_id}",
            )

    def settle_due(self, actor, event_id: int | None = None) -> None:
        """场次结束后，已通过且未签到的报名记为已缺席。"""
        with self.database.immediate() as conn:
            targets = self._settle_targets(conn, actor, event_id)
            for event in targets:
                self.settle_event(conn, actor, event)

    def settle_event(self, conn, actor, event) -> None:
        """结算一个已发布活动。全部场次结束后活动改为已结束。"""
        if event.status != EventStatus.PUBLISHED:
            return
        sessions = repo.sessions_of(conn, event.id)
        if not sessions:
            return
        now = self.clock.now()
        still_open = False
        for session in sessions:
            if parse_time(session.end_at) > now:
                still_open = True
                continue
            for record in repo.regs_of_session(conn, session.id):
                if record.status != RegStatus.APPROVED:
                    continue
                record.transition_to(RegStatus.ABSENT)
                session.release()
                repo.save_reg(conn, record)
                self.audit.append(
                    conn, actor.id, "缺席判定", "报名记录", record.id, "成功",
                    "场次已结束且未签到", event.id,
                )
            repo.save_session(conn, session)
        if not still_open:
            event.finish()
            repo.save_event(conn, event)
            self.audit.append(
                conn, actor.id, "缺席判定", "活动", event.id, "成功",
                "全部场次已结束", event.id,
            )

    def _settle_targets(self, conn, actor, event_id: int | None):
        if event_id is None:
            if actor.role.value != "平台管理员":
                raise AppError("无权限")
            return [
                event for event in repo.list_events(conn)
                if event.status == EventStatus.PUBLISHED
            ]
        event = repo.get_event(conn, event_id)
        if not actor.can_execute("settle", event.organizer_id):
            raise AppError("无权限")
        return [event]

    def _promote_earliest(self, conn, session, event):
        waiting = repo.earliest_wait(conn, session.id)
        if waiting is None or not session.has_seat():
            return None
        ticket = repo.get_ticket(conn, waiting.ticket_id)
        waiting.transition_to(RegStatus.APPROVED)
        session.leave_waitlist()
        session.occupy()
        if not ticket.is_free and waiting.payment is None:
            waiting.payment = PayStatus.UNPAID
        repo.save_reg(conn, waiting)
        self.notify.add(
            conn, waiting.user_id, NoticeType.PROMOTED, event.id, session.id,
            f"您已从候补递补成功，活动「{event.title}」，报名号 {waiting.code}",
            f"promote:{waiting.id}",
        )
        return waiting

    def _review_notice(self, conn, record, event, session_id: int, accept: bool) -> None:
        if record.status == RegStatus.APPROVED:
            content = f"您报名的「{event.title}」已通过，报名号 {record.code}"
        elif record.status == RegStatus.WAITLIST:
            content = f"「{event.title}」审核时名额已满，报名号 {record.code} 已转入候补"
        else:
            content = f"您报名的「{event.title}」未通过，原因：{record.reason}"
        self.notify.add(
            conn, record.user_id, NoticeType.REVIEW, event.id, session_id, content,
            f"review:{record.id}:{record.status.value}",
        )
        if not accept and record.status != RegStatus.CANCELLED:
            raise AppError("审核结果异常")

    def _preview(self, session_id: int, ticket_id: int) -> dict:
        conn = self.database.connect()
        try:
            session = repo.get_session(conn, session_id)
            event = repo.get_event(conn, session.event_id)
            ticket = repo.get_ticket(conn, ticket_id)
        finally:
            conn.close()
        if ticket.session_id != session.id:
            raise AppError("票种不属于该场次")
        return {"event": event, "session": session, "ticket": ticket}

    def _event_id_of_reg(self, reg_id: int) -> int:
        conn = self.database.connect()
        try:
            record = repo.get_reg(conn, reg_id)
            session = repo.get_session(conn, record.session_id)
            return session.event_id
        finally:
            conn.close()

    def _closed_reason(self, event, session) -> str | None:
        now = self.clock.now()
        if event.status == EventStatus.CANCELLED:
            return "活动已取消"
        if event.status == EventStatus.OFFLINE:
            return "活动已下架，已停止报名"
        if event.status == EventStatus.ENDED:
            return "活动已结束"
        if event.status != EventStatus.PUBLISHED:
            return "活动未发布"
        if now > parse_time(session.deadline):
            return "报名已截止"
        if now >= parse_time(session.end_at):
            return "场次已结束"
        return None

    def _log_cancel(self, conn, actor, record, event_id: int) -> None:
        self.audit.append(
            conn, actor.id, "取消报名", "报名记录", record.id,
            "成功", record.reason, event_id,
        )

    def _reject(
        self, actor, action, target_type, target_id, event_id, detail: str
    ) -> NoReturn:
        self.audit.append_own(
            actor.id, action, target_type, target_id, "拒绝", detail, event_id
        )
        raise AppError(detail)
