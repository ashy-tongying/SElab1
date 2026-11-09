# -*- coding: utf-8 -*-
"""行与领域对象的转换。服务层通过这里读写，界面不直接碰表。"""

from __future__ import annotations

import sqlite3
import uuid

from ticketapp.errors import AppError
from ticketapp.models import (
    AuditEntry,
    ChangeItem,
    ChangeRequest,
    ChangeStatus,
    CheckinGrant,
    CheckinRecord,
    Event,
    EventStatus,
    Notification,
    NoticeType,
    PayStatus,
    Registration,
    RegStatus,
    Role,
    Session,
    TicketType,
    User,
)


def _need(row: sqlite3.Row | None, what: str):
    if row is None:
        raise AppError(f"{what}不存在")
    return row


def user_from(row: sqlite3.Row) -> User:
    """用户行转对象。"""
    return User(
        id=row["id"],
        username=row["username"],
        phone=row["phone"],
        password_digest=row["password_digest"],
        role=Role(row["role"]),
        enabled=bool(row["enabled"]),
    )


def event_from(row: sqlite3.Row) -> Event:
    """活动行转对象。"""
    return Event(
        id=row["id"],
        organizer_id=row["organizer_id"],
        title=row["title"],
        category=row["category"],
        city=row["city"],
        intro=row["intro"],
        cover=row["cover"],
        status=EventStatus(row["status"]),
        need_review=bool(row["need_review"]),
        reject_reason=row["reject_reason"],
    )


def session_from(row: sqlite3.Row) -> Session:
    """场次行转对象。"""
    return Session(
        id=row["id"],
        event_id=row["event_id"],
        name=row["name"],
        start_at=row["start_at"],
        end_at=row["end_at"],
        deadline=row["deadline"],
        place=row["place"],
        capacity=row["capacity"],
        enrolled=row["enrolled"],
        waitlist=row["waitlist"],
    )


def ticket_from(row: sqlite3.Row) -> TicketType:
    """票种行转对象。"""
    return TicketType(
        id=row["id"],
        session_id=row["session_id"],
        name=row["name"],
        price=float(row["price"]),
        is_free=bool(row["is_free"]),
    )


def reg_from(row: sqlite3.Row) -> Registration:
    """报名行转对象。"""
    payment = PayStatus(row["payment_status"]) if row["payment_status"] else None
    return Registration(
        id=row["id"],
        code=row["code"],
        user_id=row["user_id"],
        session_id=row["session_id"],
        ticket_id=row["ticket_id"],
        status=RegStatus(row["status"]),
        reason=row["reason"],
        payment=payment,
        waitlist_at=row["waitlist_at"],
        created_at=row["created_at"],
    )


def get_user(conn: sqlite3.Connection, user_id: int) -> User:
    """按编号取用户。"""
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return user_from(_need(row, "用户"))


def get_user_by_name(conn: sqlite3.Connection, username: str) -> User | None:
    """按用户名取用户。"""
    row = conn.execute(
        "SELECT * FROM users WHERE username=?", (username,)
    ).fetchone()
    return user_from(row) if row else None


def insert_user(
    conn: sqlite3.Connection,
    username: str,
    phone: str,
    digest: str,
    role: Role,
) -> User:
    """新增用户。"""
    try:
        cur = conn.execute(
            """INSERT INTO users (username, phone, password_digest, role, enabled)
               VALUES (?, ?, ?, ?, 1)""",
            (username, phone, digest, role.value),
        )
    except sqlite3.IntegrityError as exc:
        raise AppError("用户名已存在") from exc
    return get_user(conn, int(cur.lastrowid))


def save_user_flags(conn: sqlite3.Connection, user: User) -> None:
    """只更新角色和启用状态。"""
    conn.execute(
        "UPDATE users SET role=?, enabled=? WHERE id=?",
        (user.role.value, 1 if user.enabled else 0, user.id),
    )


def list_users(conn: sqlite3.Connection) -> list[User]:
    """全部用户，管理页使用。"""
    rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [user_from(row) for row in rows]


def get_event(conn: sqlite3.Connection, event_id: int) -> Event:
    """按编号取活动。"""
    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    return event_from(_need(row, "活动"))


def insert_event(conn: sqlite3.Connection, event: Event) -> Event:
    """新建草稿活动。编号由数据库生成。"""
    cur = conn.execute(
        """INSERT INTO events
           (organizer_id, title, category, city, intro, cover, status,
            need_review, reject_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event.organizer_id,
            event.title,
            event.category,
            event.city,
            event.intro,
            event.cover,
            event.status.value,
            1 if event.need_review else 0,
            event.reject_reason,
        ),
    )
    return get_event(conn, int(cur.lastrowid))


def save_event(conn: sqlite3.Connection, event: Event) -> None:
    """写回活动资料和状态。"""
    conn.execute(
        """UPDATE events
           SET title=?, category=?, city=?, intro=?, cover=?, status=?,
               need_review=?, reject_reason=?
           WHERE id=?""",
        (
            event.title,
            event.category,
            event.city,
            event.intro,
            event.cover,
            event.status.value,
            1 if event.need_review else 0,
            event.reject_reason,
            event.id,
        ),
    )


def list_events(conn: sqlite3.Connection) -> list[Event]:
    """全部活动。"""
    rows = conn.execute("SELECT * FROM events ORDER BY id DESC").fetchall()
    return [event_from(row) for row in rows]


def get_session(conn: sqlite3.Connection, session_id: int) -> Session:
    """按编号取场次。事务内再读一次，不用页面上的旧余量。"""
    row = conn.execute(
        "SELECT * FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    return session_from(_need(row, "场次"))


def sessions_of(conn: sqlite3.Connection, event_id: int) -> list[Session]:
    """活动下的场次。"""
    rows = conn.execute(
        "SELECT * FROM sessions WHERE event_id=? ORDER BY start_at, id",
        (event_id,),
    ).fetchall()
    return [session_from(row) for row in rows]


def insert_session(conn: sqlite3.Connection, session: Session) -> Session:
    """新增场次。"""
    cur = conn.execute(
        """INSERT INTO sessions
           (event_id, name, start_at, end_at, deadline, place, capacity, enrolled, waitlist)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)""",
        (
            session.event_id,
            session.name,
            session.start_at,
            session.end_at,
            session.deadline,
            session.place,
            session.capacity,
        ),
    )
    return get_session(conn, int(cur.lastrowid))


def save_session(conn: sqlite3.Connection, session: Session) -> None:
    """写回场次，含容量和两个计数。"""
    conn.execute(
        """UPDATE sessions
           SET name=?, start_at=?, end_at=?, deadline=?, place=?,
               capacity=?, enrolled=?, waitlist=?
           WHERE id=?""",
        (
            session.name,
            session.start_at,
            session.end_at,
            session.deadline,
            session.place,
            session.capacity,
            session.enrolled,
            session.waitlist,
            session.id,
        ),
    )


def delete_session_row(conn: sqlite3.Connection, session_id: int) -> None:
    """删除场次及其票种。调用方保证没有报名。"""
    conn.execute("DELETE FROM tickets WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> TicketType:
    """按编号取票种。"""
    row = conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
    return ticket_from(_need(row, "票种"))


def tickets_of(conn: sqlite3.Connection, session_id: int) -> list[TicketType]:
    """场次下的票种。"""
    rows = conn.execute(
        "SELECT * FROM tickets WHERE session_id=? ORDER BY id", (session_id,)
    ).fetchall()
    return [ticket_from(row) for row in rows]


def tickets_of_event(conn: sqlite3.Connection, event_id: int) -> list[TicketType]:
    """活动全部票种。"""
    rows = conn.execute(
        """SELECT t.* FROM tickets t
           JOIN sessions s ON s.id = t.session_id
           WHERE s.event_id=? ORDER BY t.id""",
        (event_id,),
    ).fetchall()
    return [ticket_from(row) for row in rows]


def insert_ticket(conn: sqlite3.Connection, ticket: TicketType) -> TicketType:
    """新增票种。同一场次名称不能重复。"""
    try:
        cur = conn.execute(
            """INSERT INTO tickets (session_id, name, price, is_free)
               VALUES (?, ?, ?, ?)""",
            (
                ticket.session_id,
                ticket.name,
                ticket.price,
                1 if ticket.is_free else 0,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise AppError("同一场次票种名称不能重复") from exc
    return get_ticket(conn, int(cur.lastrowid))


def save_ticket(conn: sqlite3.Connection, ticket: TicketType) -> None:
    """写回票种。"""
    try:
        conn.execute(
            "UPDATE tickets SET name=?, price=?, is_free=? WHERE id=?",
            (ticket.name, ticket.price, 1 if ticket.is_free else 0, ticket.id),
        )
    except sqlite3.IntegrityError as exc:
        raise AppError("同一场次票种名称不能重复") from exc


def delete_ticket_row(conn: sqlite3.Connection, ticket_id: int) -> None:
    """删除票种。"""
    conn.execute("DELETE FROM tickets WHERE id=?", (ticket_id,))


def count_regs_for_ticket(conn: sqlite3.Connection, ticket_id: int) -> int:
    """票种是否已被报名引用。"""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM registrations WHERE ticket_id=?", (ticket_id,)
    ).fetchone()
    return int(row["n"])


def count_regs_for_session(conn: sqlite3.Connection, session_id: int) -> int:
    """场次是否已有报名。"""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM registrations WHERE session_id=?",
        (session_id,),
    ).fetchone()
    return int(row["n"])


def get_reg(conn: sqlite3.Connection, reg_id: int) -> Registration:
    """按编号取报名。"""
    row = conn.execute(
        "SELECT * FROM registrations WHERE id=?", (reg_id,)
    ).fetchone()
    return reg_from(_need(row, "报名记录"))


def get_reg_by_code(conn: sqlite3.Connection, code: str) -> Registration | None:
    """按报名号取报名。"""
    row = conn.execute(
        "SELECT * FROM registrations WHERE code=?", (code.strip(),)
    ).fetchone()
    return reg_from(row) if row else None


def active_reg(
    conn: sqlite3.Connection, user_id: int, session_id: int
) -> Registration | None:
    """该用户在本场次的有效报名。"""
    row = conn.execute(
        """SELECT * FROM registrations
           WHERE user_id=? AND session_id=? AND status IN ('待审核','已通过','候补中')
           LIMIT 1""",
        (user_id, session_id),
    ).fetchone()
    return reg_from(row) if row else None


def insert_reg(
    conn: sqlite3.Connection,
    user_id: int,
    session_id: int,
    ticket_id: int,
    status: RegStatus,
    payment: PayStatus | None,
    waitlist_at: str | None,
    created_at: str,
) -> Registration:
    """插入报名并生成报名号。"""
    placeholder = "TMP" + uuid.uuid4().hex[:16]
    cur = conn.execute(
        """INSERT INTO registrations
           (code, user_id, session_id, ticket_id, status, reason,
            payment_status, waitlist_at, created_at)
           VALUES (?, ?, ?, ?, ?, '', ?, ?, ?)""",
        (
            placeholder,
            user_id,
            session_id,
            ticket_id,
            status.value,
            payment.value if payment else None,
            waitlist_at,
            created_at,
        ),
    )
    reg_id = int(cur.lastrowid)
    code = f"BM{reg_id:08d}"
    conn.execute("UPDATE registrations SET code=? WHERE id=?", (code, reg_id))
    return get_reg(conn, reg_id)


def save_reg(conn: sqlite3.Connection, reg: Registration) -> None:
    """写回报名状态、原因和支付状态。"""
    conn.execute(
        """UPDATE registrations
           SET status=?, reason=?, payment_status=?, waitlist_at=?
           WHERE id=?""",
        (
            reg.status.value,
            reg.reason,
            reg.payment.value if reg.payment else None,
            reg.waitlist_at,
            reg.id,
        ),
    )


def earliest_wait(conn: sqlite3.Connection, session_id: int) -> Registration | None:
    """按进入候补的时间取最早一条。"""
    row = conn.execute(
        """SELECT * FROM registrations
           WHERE session_id=? AND status='候补中'
           ORDER BY waitlist_at ASC, id ASC LIMIT 1""",
        (session_id,),
    ).fetchone()
    return reg_from(row) if row else None


def regs_of_session(conn: sqlite3.Connection, session_id: int) -> list[Registration]:
    """场次全部报名。"""
    rows = conn.execute(
        "SELECT * FROM registrations WHERE session_id=? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [reg_from(row) for row in rows]


def regs_of_user(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    """参与者查看自己的报名，带活动名和票种。"""
    return conn.execute(
        """SELECT r.*, e.title AS event_title, e.id AS event_id,
                  s.name AS session_name, s.deadline AS deadline,
                  t.name AS ticket_name
           FROM registrations r
           JOIN sessions s ON s.id = r.session_id
           JOIN events e ON e.id = s.event_id
           JOIN tickets t ON t.id = r.ticket_id
           WHERE r.user_id=?
           ORDER BY r.id DESC""",
        (user_id,),
    ).fetchall()


def roster_rows(conn: sqlite3.Connection, event_id: int) -> list[sqlite3.Row]:
    """报名名单原始行。手机号由统计服务脱敏。"""
    return conn.execute(
        """SELECT r.*, u.username, u.phone, s.name AS session_name,
                  t.name AS ticket_name
           FROM registrations r
           JOIN users u ON u.id = r.user_id
           JOIN sessions s ON s.id = r.session_id
           JOIN tickets t ON t.id = r.ticket_id
           WHERE s.event_id=?
           ORDER BY s.start_at, r.id""",
        (event_id,),
    ).fetchall()


def count_status(conn: sqlite3.Connection, session_id: int, status: str) -> int:
    """按状态计数。"""
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM registrations
           WHERE session_id=? AND status=?""",
        (session_id, status),
    ).fetchone()
    return int(row["n"])


def count_by_ticket(conn: sqlite3.Connection, session_id: int) -> list[sqlite3.Row]:
    """按票种统计仍有效或已履约的报名。"""
    return conn.execute(
        """SELECT t.id, t.name, COUNT(r.id) AS n
           FROM tickets t
           LEFT JOIN registrations r
             ON r.ticket_id = t.id
            AND r.status IN ('待审核','已通过','候补中','已签到','已缺席')
           WHERE t.session_id=?
           GROUP BY t.id, t.name
           ORDER BY t.id""",
        (session_id,),
    ).fetchall()


def receivers_of_event(
    conn: sqlite3.Connection, event_id: int, statuses: tuple[str, ...]
) -> list[int]:
    """某活动下指定状态报名的用户，去重。"""
    marks = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""SELECT DISTINCT r.user_id
            FROM registrations r
            JOIN sessions s ON s.id = r.session_id
            WHERE s.event_id=? AND r.status IN ({marks})""",
        (event_id, *statuses),
    ).fetchall()
    return [int(row["user_id"]) for row in rows]


def insert_change(
    conn: sqlite3.Connection,
    event_id: int,
    applicant_id: int,
    note: str,
    created_at: str,
    items: list[tuple[str, int, str, str, str]],
) -> ChangeRequest:
    """写入变更申请和变更项。items 为类型、对象、字段、原值、新值。"""
    cur = conn.execute(
        """INSERT INTO change_requests
           (event_id, applicant_id, status, note, review_comment, created_at)
           VALUES (?, ?, '待审核', ?, '', ?)""",
        (event_id, applicant_id, note, created_at),
    )
    request_id = int(cur.lastrowid)
    for target_type, target_id, field, old_value, new_value in items:
        conn.execute(
            """INSERT INTO change_items
               (request_id, target_type, target_id, field, old_value, new_value)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (request_id, target_type, target_id, field, old_value, new_value),
        )
    return get_change(conn, request_id)


def get_change(conn: sqlite3.Connection, request_id: int) -> ChangeRequest:
    """取变更申请。"""
    row = conn.execute(
        "SELECT * FROM change_requests WHERE id=?", (request_id,)
    ).fetchone()
    row = _need(row, "变更申请")
    return ChangeRequest(
        id=row["id"],
        event_id=row["event_id"],
        applicant_id=row["applicant_id"],
        status=ChangeStatus(row["status"]),
        note=row["note"],
        reviewer_id=row["reviewer_id"],
        review_comment=row["review_comment"],
        created_at=row["created_at"],
    )


def change_items(conn: sqlite3.Connection, request_id: int) -> list[ChangeItem]:
    """申请下的变更项。"""
    rows = conn.execute(
        "SELECT * FROM change_items WHERE request_id=? ORDER BY id",
        (request_id,),
    ).fetchall()
    return [
        ChangeItem(
            id=row["id"],
            request_id=row["request_id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            field=row["field"],
            old_value=row["old_value"],
            new_value=row["new_value"],
        )
        for row in rows
    ]


def save_change(conn: sqlite3.Connection, request: ChangeRequest) -> None:
    """写回审核结果。"""
    conn.execute(
        """UPDATE change_requests
           SET status=?, reviewer_id=?, review_comment=? WHERE id=?""",
        (
            request.status.value,
            request.reviewer_id,
            request.review_comment,
            request.id,
        ),
    )


def pending_change(conn: sqlite3.Connection, event_id: int) -> ChangeRequest | None:
    """活动是否已有待审核变更。"""
    row = conn.execute(
        """SELECT * FROM change_requests
           WHERE event_id=? AND status='待审核' ORDER BY id DESC LIMIT 1""",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return get_change(conn, row["id"])


def list_changes(conn: sqlite3.Connection, status: str | None) -> list[ChangeRequest]:
    """变更申请列表。"""
    if status:
        rows = conn.execute(
            "SELECT * FROM change_requests WHERE status=? ORDER BY id DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM change_requests ORDER BY id DESC"
        ).fetchall()
    return [get_change(conn, row["id"]) for row in rows]


def insert_grant(
    conn: sqlite3.Connection,
    event_id: int,
    user_id: int,
    granted_by: int,
    granted_at: str,
) -> CheckinGrant:
    """指定本活动检票人员。"""
    try:
        cur = conn.execute(
            """INSERT INTO grants (event_id, user_id, granted_by, granted_at)
               VALUES (?, ?, ?, ?)""",
            (event_id, user_id, granted_by, granted_at),
        )
    except sqlite3.IntegrityError as exc:
        raise AppError("该用户已获得本活动检票授权") from exc
    return get_grant(conn, int(cur.lastrowid))


def get_grant(conn: sqlite3.Connection, grant_id: int) -> CheckinGrant:
    """取授权。"""
    row = conn.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
    row = _need(row, "检票授权")
    return CheckinGrant(
        id=row["id"],
        event_id=row["event_id"],
        user_id=row["user_id"],
        granted_by=row["granted_by"],
        granted_at=row["granted_at"],
    )


def find_grant(
    conn: sqlite3.Connection, event_id: int, user_id: int
) -> CheckinGrant | None:
    """某人是否被授权核销该活动。"""
    row = conn.execute(
        "SELECT * FROM grants WHERE event_id=? AND user_id=?",
        (event_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return get_grant(conn, row["id"])


def grants_of_user(conn: sqlite3.Connection, user_id: int) -> list[CheckinGrant]:
    """某人拿到的全部检票授权。"""
    rows = conn.execute(
        "SELECT * FROM grants WHERE user_id=? ORDER BY id", (user_id,)
    ).fetchall()
    return [get_grant(conn, row["id"]) for row in rows]


def insert_checkin(
    conn: sqlite3.Connection, registration_id: int, checker_id: int, checked_at: str
) -> CheckinRecord:
    """成功签到只插入一条。"""
    try:
        cur = conn.execute(
            """INSERT INTO checkins (registration_id, checker_id, checked_at)
               VALUES (?, ?, ?)""",
            (registration_id, checker_id, checked_at),
        )
    except sqlite3.IntegrityError as exc:
        raise AppError("已签到") from exc
    row = conn.execute(
        "SELECT * FROM checkins WHERE id=?", (cur.lastrowid,)
    ).fetchone()
    return CheckinRecord(
        id=row["id"],
        registration_id=row["registration_id"],
        checker_id=row["checker_id"],
        checked_at=row["checked_at"],
    )


def insert_notice(
    conn: sqlite3.Connection,
    receiver_id: int,
    ntype: NoticeType,
    event_id: int,
    session_id: int | None,
    content: str,
    created_at: str,
    dedupe_key: str,
) -> None:
    """同一业务键不重复生成通知。"""
    exists = conn.execute(
        "SELECT 1 FROM notifications WHERE dedupe_key=?", (dedupe_key,)
    ).fetchone()
    if exists:
        return
    conn.execute(
        """INSERT INTO notifications
           (receiver_id, ntype, event_id, session_id, content, created_at, dedupe_key)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            receiver_id,
            ntype.value,
            event_id,
            session_id,
            content,
            created_at,
            dedupe_key,
        ),
    )


def list_notices(conn: sqlite3.Connection, receiver_id: int) -> list[Notification]:
    """某人的通知，新的在前。"""
    rows = conn.execute(
        """SELECT * FROM notifications WHERE receiver_id=?
           ORDER BY id DESC""",
        (receiver_id,),
    ).fetchall()
    return [_notice(row) for row in rows]


def get_notice(conn: sqlite3.Connection, notice_id: int) -> Notification:
    """取一条通知。"""
    row = conn.execute(
        "SELECT * FROM notifications WHERE id=?", (notice_id,)
    ).fetchone()
    return _notice(_need(row, "通知"))


def save_notice(conn: sqlite3.Connection, notice: Notification) -> None:
    """写回已读时间。"""
    conn.execute(
        "UPDATE notifications SET read_at=? WHERE id=?",
        (notice.read_at, notice.id),
    )


def _notice(row: sqlite3.Row) -> Notification:
    return Notification(
        id=row["id"],
        receiver_id=row["receiver_id"],
        ntype=NoticeType(row["ntype"]),
        event_id=row["event_id"],
        session_id=row["session_id"],
        content=row["content"],
        created_at=row["created_at"],
        read_at=row["read_at"],
    )


def insert_audit(
    conn: sqlite3.Connection,
    actor_id: int,
    action: str,
    target_type: str,
    target_id: int,
    result: str,
    detail: str,
    event_id: int | None,
    created_at: str,
) -> None:
    """追加日志。没有对应的更新语句。"""
    conn.execute(
        """INSERT INTO audit_logs
           (actor_id, action, target_type, target_id, result, detail, event_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            actor_id,
            action,
            target_type,
            target_id,
            result,
            detail,
            event_id,
            created_at,
        ),
    )


def query_audit(conn: sqlite3.Connection, where: str, args: tuple) -> list[AuditEntry]:
    """按调用方拼好的条件查询。调用方负责权限范围。"""
    rows = conn.execute(
        f"SELECT * FROM audit_logs WHERE {where} ORDER BY id DESC", args
    ).fetchall()
    return [
        AuditEntry(
            id=row["id"],
            actor_id=row["actor_id"],
            action=row["action"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            result=row["result"],
            detail=row["detail"],
            event_id=row["event_id"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
