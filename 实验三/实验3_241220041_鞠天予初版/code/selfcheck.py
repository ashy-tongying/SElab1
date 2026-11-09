# -*- coding: utf-8 -*-
"""按实验二的状态图和时序图检查主要规则。"""

from __future__ import annotations

import gc
import sqlite3
import tempfile
import threading
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path

from ticketapp.errors import AppError
from ticketapp.models import EventStatus, PayStatus, RegStatus, Role
from ticketapp.system import System
from ticketapp.ui import EventDesk, TicketApp


class ManualClock:
    """测试用时钟。"""

    def __init__(self) -> None:
        self.current = datetime(2026, 11, 2, 9, 0, 0)

    def now(self) -> datetime:
        """返回设定时间。"""
        return self.current


class World:
    """每个用例一个空库，只放管理员。"""

    def __init__(self) -> None:
        # 库要活到用例结束，不能写成 with。
        self.tmp = tempfile.TemporaryDirectory(  # pylint: disable=consider-using-with
            ignore_cleanup_errors=True
        )
        self.clock = ManualClock()
        self.system = System(Path(self.tmp.name) / "t.db", clock=self.clock, demo=False)
        self.admin = self.system.users.login("admin", "123456")
        self.org = self.user("org", Role.ORGANIZER, "13800000001")

    def close(self) -> None:
        """删掉临时库。Windows 上先放开数据库文件。"""
        gc.collect()
        self.tmp.cleanup()

    def user(self, name: str, role: Role, phone: str):
        """创建并登录一个用户。"""
        self.system.users.create_user(self.admin, name, phone, "123456", role)
        return self.system.users.login(name, "123456")

    def publish(self, title="讲座", capacity=2, price=0.0, need_review=False, city="南京"):
        """创建并发布一个只有一场的活动。"""
        event = self.system.events.create_event(
            self.org, title, "文艺", city, "用于规则检查的活动介绍。", "", need_review
        )
        session = self.system.events.add_session(
            self.org, event.id, "主场", "报告厅",
            "2026-11-10 09:00", "2026-11-10 18:00", "2026-11-08 18:00", capacity,
        )
        ticket = self.system.events.add_ticket(self.org, session.id, "普通票", price)
        self.system.events.submit(self.org, event.id)
        self.system.events.approve(self.admin, event.id)
        return event, session, ticket


def expect(action, text: str) -> None:
    """操作必须失败，且提示里包含指定原因。"""
    try:
        action()
    except AppError as exc:
        if text not in str(exc):
            raise AssertionError(f"期望提示包含「{text}」，实际是「{exc}」") from exc
        return
    raise AssertionError(f"应当被拒绝：{text}")


def counts(world: World, session_id: int) -> tuple[int, int]:
    """核对场次上的两个计数和报名行一致。"""
    conn = world.system.database.connect()
    try:
        session = conn.execute(
            "SELECT enrolled, waitlist FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        approved = _count(conn, session_id, "已通过")
        checked = _count(conn, session_id, "已签到")
        waiting = _count(conn, session_id, "候补中")
        if session["enrolled"] != approved + checked:
            raise AssertionError("已报名数和已通过、已签到不一致")
        if session["waitlist"] != waiting:
            raise AssertionError("候补数和候补中的记录不一致")
        if session["enrolled"] > conn.execute(
            "SELECT capacity FROM sessions WHERE id=?", (session_id,)
        ).fetchone()["capacity"]:
            raise AssertionError("已报名数超过容量")
        return session["enrolled"], session["waitlist"]
    finally:
        conn.close()


def _count(conn, session_id: int, status: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM registrations WHERE session_id=? AND status=?",
        (session_id, status),
    ).fetchone()
    return int(row["n"])


def test_permissions() -> None:
    """四类角色越权会被拒绝。"""
    world = World()
    try:
        person = world.user("lin", Role.PARTICIPANT, "13900000001")
        checker = world.user("chk", Role.CHECKER, "13700000001")
        expect(lambda: world.system.events.create_event(
            person, "x", "文艺", "南京", "介绍不够。", "", False
        ), "只有组织者")
        event, session, ticket = world.publish()
        expect(lambda: world.system.events.approve(world.org, event.id), "无权限")
        record = world.system.regs.register(person, session.id, ticket.id)
        expect(lambda: world.system.checkin.redeem(checker, record.code), "不是本活动")
        expect(lambda: world.system.stats.export_csv(checker, event.id, True), "不能导出")
        expect(lambda: world.system.stats.export_csv(person, event.id, True), "无权限")
        expect(lambda: world.system.audit.query(person, actor_id=world.admin.id), "无权限")
    finally:
        world.close()


def test_publish_flow() -> None:
    """不完整不能提交；驳回后可再交；参与者看不到未发布活动。"""
    world = World()
    try:
        person = world.user("lin", Role.PARTICIPANT, "13900000001")
        event = world.system.events.create_event(
            world.org, "未完成", "文艺", "南京", "", "", False
        )
        expect(lambda: world.system.events.submit(world.org, event.id), "不完整")
        session = world.system.events.add_session(
            world.org, event.id, "主场", "报告厅",
            "2026-11-10 09:00", "2026-11-10 18:00", "2026-11-08 18:00", 10,
        )
        expect(lambda: world.system.events.add_ticket(world.org, session.id, "普通票", -1), "不能为负")
        world.system.events.add_ticket(world.org, session.id, "普通票", 0)
        expect(
            lambda: world.system.events.add_ticket(world.org, session.id, "普通票", 0),
            "不能重复",
        )
        world.system.events.update_profile(
            world.org, event.id, "未完成", "文艺", "南京", "补充后的介绍。", "", False
        )
        world.system.events.submit(world.org, event.id)
        hidden = world.system.events.search(person, keyword="未完成")
        if hidden:
            raise AssertionError("待审核活动不该被参与者搜到")
        world.system.events.reject(world.admin, event.id, "介绍太少")
        rejected = world.system.events.detail(world.org, event.id)["event"]
        if rejected.status != EventStatus.REJECTED or "介绍太少" not in rejected.reject_reason:
            raise AssertionError("驳回原因没有记下")
        world.system.events.submit(world.org, event.id)
        promoted = world.system.users.set_role(world.admin, world.org.id, Role.ADMIN, True)
        expect(lambda: world.system.events.approve(promoted, event.id), "不能审核自己")
    finally:
        world.close()


def test_register_review_and_waitlist() -> None:
    """审核、满员候补、取消后自动递补。"""
    world = World()
    try:
        first = world.user("aa", Role.PARTICIPANT, "13900000001")
        second = world.user("bb", Role.PARTICIPANT, "13900000002")
        third = world.user("cc", Role.PARTICIPANT, "13900000003")
        _event, session, ticket = world.publish("需审核", capacity=1, need_review=True)
        pending = world.system.regs.register(first, session.id, ticket.id)
        if pending.status != RegStatus.PENDING or counts(world, session.id) != (0, 0):
            raise AssertionError("待审核不应占名额")
        world.system.regs.review(world.org, pending.id, True)
        if counts(world, session.id)[0] != 1:
            raise AssertionError("通过后应占用名额")
        later = world.system.regs.register(second, session.id, ticket.id)
        moved = world.system.regs.review(world.org, later.id, True)
        if moved.status != RegStatus.WAITLIST or counts(world, session.id) != (1, 1):
            raise AssertionError("满员通过时应转入候补")
        notices = world.system.notify.list_mine(second)
        if not any(item.ntype.value == "审核结果" for item in notices):
            raise AssertionError("审核结果应写通知")
        expect(lambda: world.system.regs.register(first, session.id, ticket.id), "已报名")
        denied = world.system.regs.register(third, session.id, ticket.id)
        world.system.regs.review(world.org, denied.id, False, "资料不全")
        again = world.system.regs.register(third, session.id, ticket.id)
        if again.status != RegStatus.PENDING:
            raise AssertionError("拒绝后应允许重新报名")
        expect(lambda: world.system.regs.promote_manual(world.org, moved.id), "没有剩余名额")
        world.system.regs.cancel(first, pending.id)
        promoted = world.system.regs.list_mine(second)[0]
        if promoted["status"] != "已通过" or counts(world, session.id) != (1, 0):
            raise AssertionError("取消后应递补最早的候补，待审核不占候补数")
        got = world.system.notify.list_mine(second)
        if not any(item.ntype.value == "递补成功" for item in got):
            raise AssertionError("递补应写通知")
    finally:
        world.close()


def test_manual_promote_respects_order() -> None:
    """有更早候补时，不能手动插队。"""
    world = World()
    try:
        users = [
            world.user(f"p{i}", Role.PARTICIPANT, f"1390000001{i}") for i in range(4)
        ]
        _event, session, ticket = world.publish("名额", capacity=2)
        records = [
            world.system.regs.register(user, session.id, ticket.id) for user in users
        ]
        if [item.status for item in records[:2]] != [RegStatus.APPROVED, RegStatus.APPROVED]:
            raise AssertionError("前两人应直接通过")
        if records[2].status != RegStatus.WAITLIST or records[3].status != RegStatus.WAITLIST:
            raise AssertionError("后两人应候补")
        world.system.events.request_change(
            world.org, _event.id, [("场次", session.id, "容量", "3")], "增加一个名额"
        )
        request = world.system.events.pending_changes(world.admin)[0]
        still = world.system.events.detail(world.org, _event.id)["sessions"][0]
        if still.capacity != 2:
            raise AssertionError("审核前容量不能变")
        world.system.events.review_change(world.admin, request.id, True, "同意", True)
        updated = world.system.events.detail(world.org, _event.id)["sessions"][0]
        if updated.capacity != 3:
            raise AssertionError("审核通过后容量应生效")
        expect(
            lambda: world.system.regs.promote_manual(world.org, records[3].id),
            "自动递补优先",
        )
        world.system.regs.promote_manual(world.org, records[2].id)
        if counts(world, session.id) != (3, 1):
            raise AssertionError("只能递补最早的一位")
    finally:
        world.close()


def test_payment_change_and_export() -> None:
    """收费票支付、关键信息变更和脱敏导出。"""
    world = World()
    try:
        person = world.user("lin", Role.PARTICIPANT, "13912348002")
        event = world.system.events.create_event(
            world.org, "演唱会", "文艺", "南京", "用于规则检查的活动介绍。", "", False
        )
        session = world.system.events.add_session(
            world.org, event.id, "主场", "报告厅",
            "2026-11-10 09:00", "2026-11-10 18:00", "2026-11-08 18:00", 10,
        )
        free = world.system.events.add_ticket(world.org, session.id, "普通票", 0)
        paid = world.system.events.add_ticket(world.org, session.id, "前排票", 20)
        world.system.events.submit(world.org, event.id)
        world.system.events.approve(world.admin, event.id)
        free_reg = world.system.regs.register(person, session.id, free.id)
        expect(lambda: world.system.regs.mark_paid(world.org, free_reg.id, True), "免费票")
        other = world.user("zhou", Role.PARTICIPANT, "13712348003")
        paid_reg = world.system.regs.register(other, session.id, paid.id)
        if paid_reg.payment != PayStatus.UNPAID:
            raise AssertionError("收费票报名后应为待支付")
        world.system.regs.mark_paid(world.org, paid_reg.id, True)
        world.system.regs.mark_paid(world.admin, paid_reg.id, True)
        expect(
            lambda: world.system.events.update_ticket(world.org, paid.id, "前排票", 30),
            "变更申请",
        )
        world.system.events.request_change(
            world.org, event.id, [("票种", paid.id, "价格", "30")], "调整票价"
        )
        price_now = world.system.events.detail(world.org, event.id)["tickets"][session.id]
        if any(item.name == "前排票" and item.price != 20 for item in price_now):
            raise AssertionError("审核前价格必须保持原值")
        request = world.system.events.changes_of(world.org, event.id)[0]
        world.system.events.review_change(world.admin, request.id, True, "通过", True)
        after = world.system.events.detail(world.org, event.id)["tickets"][session.id]
        front = next(item for item in after if item.name == "前排票")
        if front.price != 30 or front.is_free:
            raise AssertionError("变更通过后价格应生效")
        notices = world.system.notify.list_mine(other)
        if not any(item.ntype.value == "关键信息变更" for item in notices):
            raise AssertionError("已报名用户应收到变更通知")
        text = world.system.stats.export_csv(world.org, event.id, True)
        if "13912348002" in text or "139****8002" not in text:
            raise AssertionError("导出手机号应脱敏")
        expect(lambda: world.system.stats.export_csv(world.org, event.id, False), "二次确认")
        logs = world.system.audit.query(world.admin, action="名单导出", event_id=event.id)
        if not logs:
            raise AssertionError("导出必须记日志")
    finally:
        world.close()


def test_checkin_and_cancel_event() -> None:
    """签到、重复签到、下架和活动取消。"""
    world = World()
    try:
        person = world.user("lin", Role.PARTICIPANT, "13900000001")
        other = world.user("zhou", Role.PARTICIPANT, "13900000002")
        waiting = world.user("chen", Role.PARTICIPANT, "13900000003")
        outsider = world.user("wai", Role.PARTICIPANT, "13900000004")
        event, session, ticket = world.publish("签到场", capacity=2, price=20)
        approved = world.system.regs.register(person, session.id, ticket.id)
        payer = world.system.regs.register(other, session.id, ticket.id)
        queued = world.system.regs.register(waiting, session.id, ticket.id)
        if payer.status != RegStatus.APPROVED or queued.status != RegStatus.WAITLIST:
            raise AssertionError("两人应通过，第三人应候补")
        world.system.regs.mark_paid(world.org, payer.id, True)
        expect(lambda: world.system.checkin.redeem(person, approved.code), "不是本活动")
        world.system.users.grant_checker(world.org, event.id, person.id)
        result = world.system.checkin.redeem(person, approved.code)
        if result["username"] != "lin":
            raise AssertionError("签到结果应带回用户名")
        expect(lambda: world.system.checkin.redeem(person, approved.code), "已签到")
        repeat_logs = world.system.audit.query(world.admin, action="重复签到")
        if not repeat_logs:
            raise AssertionError("重复签到要单独记日志")
        conn = world.system.database.connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM checkins WHERE registration_id=?",
                (approved.id,),
            ).fetchone()
            if row["n"] != 1:
                raise AssertionError("重复签到不能新增第二条签到记录")
        finally:
            conn.close()
        world.system.events.take_offline(world.admin, event.id, True)
        expect(
            lambda: world.system.regs.register(outsider, session.id, ticket.id),
            "已下架",
        )
        world.system.events.cancel_event(world.admin, event.id, True)
        mine = world.system.regs.list_mine(person)[0]
        if mine["status"] != "已签到":
            raise AssertionError("已签到在活动取消后应保留")
        refunded = world.system.regs.list_mine(other)[0]
        queued_now = world.system.regs.list_mine(waiting)[0]
        if refunded["status"] != "已失效" or refunded["payment_status"] != "待退款":
            raise AssertionError("未签到的收费票应失效并标记待退款")
        if queued_now["status"] != "已失效" or counts(world, session.id) != (1, 0):
            raise AssertionError("候补应清空，已签到仍占已报名数")
        expect(lambda: world.system.events.cancel_event(world.org, event.id, True), "不能重复取消")
        expect(
            lambda: world.system.regs.register(outsider, session.id, ticket.id),
            "活动已取消",
        )
        notice = world.system.notify.list_mine(other)
        if not any(item.ntype.value == "活动取消" for item in notice):
            raise AssertionError("取消应通知已报名用户")
    finally:
        world.close()


def test_deadline_absent_and_search() -> None:
    """截止后不能报名或取消；结束后未签到记缺席；查询条件生效。"""
    world = World()
    try:
        person = world.user("lin", Role.PARTICIPANT, "13900000001")
        event, session, ticket = world.publish("检索活动", capacity=5, city="南京")
        other = world.system.events.create_event(
            world.org, "另一城", "科技", "上海", "另一座城市的活动。", "", False
        )
        world.system.events.add_session(
            world.org, other.id, "场", "上海",
            "2026-12-02 09:00", "2026-12-02 18:00", "2026-12-01 18:00", 5,
        )
        world.system.events.add_ticket(world.org, world.system.events.detail(
            world.org, other.id
        )["sessions"][0].id, "票", 0)
        world.system.events.submit(world.org, other.id)
        world.system.events.approve(world.admin, other.id)
        found = world.system.events.search(
            person, keyword="检索", city="南京", date_from="2026-11-01", date_to="2026-11-30"
        )
        if len(found) != 1 or found[0]["browse_status"] != "报名中":
            raise AssertionError("组合查询结果不对")
        if world.system.events.search(person, city="杭州"):
            raise AssertionError("没有结果时应为空")
        record = world.system.regs.register(person, session.id, ticket.id)
        world.clock.current = datetime(2026, 11, 8, 18, 0, 1)
        expect(lambda: world.system.regs.cancel(person, record.id), "已截止")
        expect(
            lambda: world.system.regs.register(
                world.user("late", Role.PARTICIPANT, "13900000008"), session.id, ticket.id
            ),
            "已截止",
        )
        world.clock.current = datetime(2026, 11, 10, 18, 0, 1)
        expect(lambda: world.system.checkin.redeem(world.org, record.code), "无权限")
        world.system.regs.settle_due(world.org, event.id)
        settled = world.system.regs.list_mine(person)[0]
        finished = world.system.events.detail(world.org, event.id)["event"]
        if settled["status"] != "已缺席" or finished.status != EventStatus.ENDED:
            raise AssertionError("结束后未签到应缺席，活动应结束")
        if counts(world, session.id) != (0, 0):
            raise AssertionError("缺席后不再占已报名数")
    finally:
        world.close()


def test_audit_immutable() -> None:
    """日志不能改、不能删。"""
    world = World()
    try:
        world.publish()
        expect(world.system.audit.refuse_update, "不能修改")
        expect(world.system.audit.refuse_delete, "不能修改")
        conn = world.system.database.connect()
        try:
            try:
                conn.execute("UPDATE audit_logs SET detail='被改'")
                conn.commit()
            except sqlite3.DatabaseError:
                return
            raise AssertionError("数据库应拒绝修改日志")
        finally:
            conn.close()
    finally:
        world.close()


def test_concurrent_capacity() -> None:
    """多人同时抢最后一个名额时不能超卖。"""
    world = World()
    try:
        _event, session, ticket = world.publish("抢票", capacity=5)
        users = [
            world.user(f"c{i:03d}", Role.PARTICIPANT, f"13{i:09d}") for i in range(1, 201)
        ]
        barrier = threading.Barrier(len(users))
        statuses: list[str] = []
        errors: list[str] = []
        lock = threading.Lock()

        def worker(user) -> None:
            barrier.wait()
            try:
                record = world.system.regs.register(user, session.id, ticket.id)
                with lock:
                    statuses.append(record.status.value)
            except AppError as exc:
                with lock:
                    errors.append(str(exc))

        threads = [threading.Thread(target=worker, args=(user,)) for user in users]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if errors:
            raise AssertionError("并发报名出现拒绝：" + errors[0])
        approved = statuses.count("已通过")
        waiting = statuses.count("候补中")
        if approved != 5 or waiting != 195 or counts(world, session.id) != (5, 195):
            raise AssertionError(f"超卖或候补数量不对：{approved} / {waiting}")
    finally:
        world.close()


def test_window_opens() -> None:
    """界面能登录，并打开组织者工作台。"""
    tmp = tempfile.TemporaryDirectory(  # pylint: disable=consider-using-with
        ignore_cleanup_errors=True
    )
    root = tk.Tk()
    try:
        app = TicketApp(root, Path(tmp.name) / "ui.db")
        root.update()
        app.sign_in("organizer", "123456")
        root.update()
        if app.actor is None or app.actor.role != Role.ORGANIZER:
            raise AssertionError("组织者登录后应进入主界面")
        for index in range(app.nav.size()):
            app.show_page(app.nav.get(index))
            root.update()
        event_id = app.system.events.list_owned(app.actor)[0].id
        desk = EventDesk(root, app.system, app.actor, event_id, lambda: None)
        root.update()
        desk.win.destroy()
        root.update()
    finally:
        root.destroy()
        tmp.cleanup()


TESTS = [
    test_permissions,
    test_publish_flow,
    test_register_review_and_waitlist,
    test_manual_promote_respects_order,
    test_payment_change_and_export,
    test_checkin_and_cancel_event,
    test_deadline_absent_and_search,
    test_audit_immutable,
    test_concurrent_capacity,
    test_window_opens,
]


def main() -> int:
    """逐项运行。有失败时返回 1。"""
    failed = 0
    for test in TESTS:
        try:
            test()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
            traceback.print_exc()
        else:
            print(f"PASS {test.__name__}")
    print(f"完成：{len(TESTS) - failed} 通过，{failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
