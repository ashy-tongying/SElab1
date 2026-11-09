# -*- coding: utf-8 -*-
"""演示数据。空库第一次启动时写入，已有数据则跳过。"""

from __future__ import annotations

from datetime import datetime, timedelta

from ticketapp.models import Role, format_time

PASSWORD = "123456"


def prepare(system, demo: bool) -> None:
    """保证至少有管理员。demo 为真时再放入示例活动和账号。"""
    system.users.ensure_admin("admin", "13800000000", PASSWORD)
    if not demo:
        return
    conn = system.database.connect()
    try:
        if system_has_organizer(conn):
            return
    finally:
        conn.close()
    admin = system.users.login("admin", PASSWORD)
    system.users.create_user(admin, "organizer", "13800001111", PASSWORD, Role.ORGANIZER)
    system.users.create_user(admin, "linxiao", "13900002222", PASSWORD, Role.PARTICIPANT)
    system.users.create_user(admin, "zhou", "13700003333", PASSWORD, Role.PARTICIPANT)
    system.users.create_user(admin, "chen", "13600004444", PASSWORD, Role.PARTICIPANT)
    system.users.create_user(admin, "checker", "13500005555", PASSWORD, Role.CHECKER)
    organizer = system.users.login("organizer", PASSWORD)
    show = _event(
        system, organizer, admin, "校园歌手大赛", "文艺", "南京",
        "学生社团年度演出，含免费票和前排票。", False, publish=True,
    )
    _event(
        system, organizer, admin, "城市编程马拉松", "科技", "上海",
        "24 小时编程活动，报名需要组织者审核，名额很少。", True, publish=True,
        capacity=2,
    )
    _event(
        system, organizer, admin, "玄武湖摄影外拍", "文艺", "南京",
        "周末外拍，提交后等待管理员审核。", False, publish=False, submit=True,
    )
    _event(
        system, organizer, admin, "周末读书会", "公益", "南京",
        "草稿，还没有提交审核。", False, publish=False, submit=False,
    )
    checker = system.users.login("checker", PASSWORD)
    system.users.grant_checker(organizer, show["event"].id, checker.id)
    linxiao = system.users.login("linxiao", PASSWORD)
    zhou = system.users.login("zhou", PASSWORD)
    system.regs.register(linxiao, show["session"].id, show["free"].id)
    system.regs.register(zhou, show["session"].id, show["paid"].id)


def system_has_organizer(conn) -> bool:
    """是否已经灌过演示账号。"""
    row = conn.execute(
        "SELECT 1 FROM users WHERE username='organizer'"
    ).fetchone()
    return row is not None


def _event(system, organizer, admin, title, category, city, intro, need_review,
           publish: bool, submit: bool = True, capacity: int = 30):
    event = system.events.create_event(
        organizer, title, category, city, intro, "", need_review
    )
    deadline, start, end = _times()
    session = system.events.add_session(
        organizer, event.id, "第一场", city + "·主会场", start, end, deadline, capacity
    )
    free = system.events.add_ticket(organizer, session.id, "免费票", 0)
    paid = None
    if capacity > 2:
        paid = system.events.add_ticket(organizer, session.id, "前排票", 20)
    if submit:
        system.events.submit(organizer, event.id)
    if publish:
        system.events.approve(admin, event.id)
    return {"event": event, "session": session, "free": free, "paid": paid}


def _times():
    now = datetime.now().replace(microsecond=0)
    deadline = format_time(now + timedelta(days=5))
    start = format_time(now + timedelta(days=6))
    end = format_time(now + timedelta(days=6, hours=3))
    return deadline, start, end
