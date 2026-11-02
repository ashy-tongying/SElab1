# -*- coding: utf-8 -*-
"""活动、场次、票种和关键信息变更。"""

from __future__ import annotations

from ticketapp.database import Database
from ticketapp.errors import AppError
from ticketapp.models import (
    ChangeStatus,
    Event,
    EventStatus,
    NoticeType,
    Session,
    TicketType,
    ensure_time_order,
    format_time,
    parse_time,
)
from ticketapp import repo

_KEY_FIELDS = {
    ("场次", "开始时间"),
    ("场次", "结束时间"),
    ("场次", "报名截止时间"),
    ("场次", "容量"),
    ("票种", "价格"),
}
_TIME_ATTR = {
    "开始时间": "start_at",
    "结束时间": "end_at",
    "报名截止时间": "deadline",
}
_BROWSE_OK = (EventStatus.PUBLISHED, EventStatus.ENDED)


class EventService:
    """活动管理。对应包图中的活动管理。"""

    def __init__(self, database: Database, audit, notify, clock, regs) -> None:
        self.database = database
        self.audit = audit
        self.notify = notify
        self.clock = clock
        self.regs = regs

    def create_event(
        self, actor, title: str, category: str, city: str,
        intro: str, cover: str, need_review: bool,
    ) -> Event:
        """组织者创建草稿。"""
        if not actor.can_execute("create_event"):
            raise AppError("只有组织者可以创建活动")
        if not title.strip() or not category.strip() or not city.strip():
            raise AppError("标题、分类和城市不能为空")
        draft = Event(
            id=0, organizer_id=actor.id, title=title.strip(),
            category=category.strip(), city=city.strip(), intro=intro.strip(),
            cover=cover.strip(), status=EventStatus.DRAFT,
            need_review=bool(need_review), reject_reason="",
        )
        with self.database.immediate() as conn:
            return repo.insert_event(conn, draft)

    def update_profile(
        self, actor, event_id: int, title: str, category: str, city: str,
        intro: str, cover: str, need_review: bool,
    ) -> Event:
        """已发布后可以改介绍等非关键信息，不能改是否审核。"""
        with self.database.immediate() as conn:
            event = self._own(conn, actor, event_id)
            if event.status in (EventStatus.DRAFT, EventStatus.REJECTED):
                self._fill_profile(event, title, category, city, intro, cover)
                event.need_review = bool(need_review)
            elif event.status == EventStatus.PUBLISHED:
                if bool(need_review) != event.need_review:
                    raise AppError("发布后不能修改报名是否需要审核")
                self._fill_profile(event, title, category, city, intro, cover)
            else:
                raise AppError("当前状态不能修改活动资料")
            repo.save_event(conn, event)
            return event

    def add_session(
        self, actor, event_id: int, name: str, place: str,
        start_at: str, end_at: str, deadline: str, capacity: int,
    ) -> Session:
        """草稿或已驳回时增加场次。"""
        start, end, stop, seats = self._session_values(
            start_at, end_at, deadline, capacity
        )
        with self.database.immediate() as conn:
            event = self._own(conn, actor, event_id)
            self._require_editable(event)
            if not name.strip() or not place.strip():
                raise AppError("场次名称和地点不能为空")
            session = Session(
                id=0, event_id=event.id, name=name.strip(), place=place.strip(),
                start_at=start, end_at=end, deadline=stop,
                capacity=seats, enrolled=0, waitlist=0,
            )
            return repo.insert_session(conn, session)

    def update_session(
        self, actor, session_id: int, name: str, place: str,
        start_at: str, end_at: str, deadline: str, capacity: int,
    ) -> Session:
        """已发布后，时间和容量必须走变更申请。"""
        start, end, stop, seats = self._session_values(
            start_at, end_at, deadline, capacity
        )
        with self.database.immediate() as conn:
            session = repo.get_session(conn, session_id)
            event = self._own(conn, actor, session.event_id)
            if not name.strip() or not place.strip():
                raise AppError("场次名称和地点不能为空")
            key_changed = (
                session.start_at != start or session.end_at != end
                or session.deadline != stop or session.capacity != seats
            )
            if event.status == EventStatus.PUBLISHED and key_changed:
                raise AppError("场次时间、容量须提交变更申请，不能直接修改")
            if seats < session.enrolled:
                raise AppError("新容量不能小于已报名数")
            if event.status not in (
                EventStatus.DRAFT, EventStatus.REJECTED, EventStatus.PUBLISHED
            ):
                raise AppError("当前状态不能修改场次")
            if event.status != EventStatus.PUBLISHED:
                self._require_editable(event)
            session.name = name.strip()
            session.place = place.strip()
            if event.status != EventStatus.PUBLISHED:
                session.start_at = start
                session.end_at = end
                session.deadline = stop
                session.capacity = seats
            repo.save_session(conn, session)
            return session

    def delete_session(self, actor, session_id: int) -> None:
        """没有报名时可以删除草稿中的场次。"""
        with self.database.immediate() as conn:
            session = repo.get_session(conn, session_id)
            event = self._own(conn, actor, session.event_id)
            self._require_editable(event)
            if repo.count_regs_for_session(conn, session.id):
                raise AppError("该场次已有报名，不能删除")
            repo.delete_session_row(conn, session.id)

    def add_ticket(self, actor, session_id: int, name: str, price: float) -> TicketType:
        """为场次添加票种。"""
        with self.database.immediate() as conn:
            session = repo.get_session(conn, session_id)
            event = self._own(conn, actor, session.event_id)
            self._require_editable(event)
            ticket = self._new_ticket(session.id, name, price)
            return repo.insert_ticket(conn, ticket)

    def update_ticket(self, actor, ticket_id: int, name: str, price: float) -> TicketType:
        """已发布后不能直接改价格。"""
        with self.database.immediate() as conn:
            ticket = repo.get_ticket(conn, ticket_id)
            session = repo.get_session(conn, ticket.session_id)
            event = self._own(conn, actor, session.event_id)
            if not name.strip():
                raise AppError("票种名称不能为空")
            price_changed = f"{float(price):.2f}" != f"{ticket.price:.2f}"
            if event.status == EventStatus.PUBLISHED and price_changed:
                raise AppError("票种价格须提交变更申请，不能直接修改")
            if event.status not in (
                EventStatus.DRAFT, EventStatus.REJECTED, EventStatus.PUBLISHED
            ):
                raise AppError("当前状态不能修改票种")
            ticket.name = name.strip()
            if event.status != EventStatus.PUBLISHED:
                ticket.set_price(price)
            repo.save_ticket(conn, ticket)
            return ticket

    def delete_ticket(self, actor, ticket_id: int) -> None:
        """删除尚未使用的票种。"""
        with self.database.immediate() as conn:
            ticket = repo.get_ticket(conn, ticket_id)
            session = repo.get_session(conn, ticket.session_id)
            event = self._own(conn, actor, session.event_id)
            self._require_editable(event)
            if repo.count_regs_for_ticket(conn, ticket.id):
                raise AppError("该票种已有报名，不能删除")
            repo.delete_ticket_row(conn, ticket.id)

    def submit(self, actor, event_id: int) -> Event:
        """信息完整后提交审核。提交后参与者仍不可见。"""
        with self.database.immediate() as conn:
            event = self._own(conn, actor, event_id)
            self._assert_complete(conn, event)
            event.submit_review()
            repo.save_event(conn, event)
            self.audit.append(
                conn, actor.id, "提交审核", "活动", event.id, "成功", "", event.id
            )
            return event

    def approve(self, actor, event_id: int) -> Event:
        """管理员通过后自动发布。不能审核自己组织的活动。"""
        with self.database.immediate() as conn:
            event = repo.get_event(conn, event_id)
            self._require_reviewer(actor, event)
            self._assert_complete(conn, event)
            event.publish()
            repo.save_event(conn, event)
            self.audit.append(
                conn, actor.id, "活动审核", "活动", event.id, "通过", "", event.id
            )
            return event

    def reject(self, actor, event_id: int, reason: str) -> Event:
        """驳回并记录原因。"""
        with self.database.immediate() as conn:
            event = repo.get_event(conn, event_id)
            self._require_reviewer(actor, event)
            event.reject(reason)
            repo.save_event(conn, event)
            self.audit.append(
                conn, actor.id, "活动审核", "活动", event.id, "驳回",
                event.reject_reason, event.id,
            )
            return event

    def take_offline(self, actor, event_id: int, confirmed: bool) -> Event:
        """下架违规活动。已有报名保留。"""
        if not actor.can_execute("offline"):
            raise AppError("无权限")
        if not confirmed:
            raise AppError("下架需要二次确认")
        with self.database.immediate() as conn:
            event = repo.get_event(conn, event_id)
            event.take_offline()
            repo.save_event(conn, event)
            self.audit.append(
                conn, actor.id, "下架", "活动", event.id, "成功", "", event.id
            )
            return event

    def cancel_event(self, actor, event_id: int, confirmed: bool) -> Event:
        """组织者取消或管理员强制取消。"""
        if not confirmed:
            raise AppError("取消活动需要二次确认")
        with self.database.immediate() as conn:
            event = repo.get_event(conn, event_id)
            if not actor.can_execute("cancel_event", event.organizer_id):
                raise AppError("无权限")
            event.cancel()
            repo.save_event(conn, event)
            self.regs.invalidate_event(conn, event)
            detail = "管理员强制取消" if actor.role.value == "平台管理员" else "组织者取消"
            self.audit.append(
                conn, actor.id, "活动取消", "活动", event.id, "成功", detail, event.id
            )
            return event

    def request_change(self, actor, event_id: int, specs: list, note: str):
        """提交场次时间、容量或票种价格的变更。审核前原值仍然有效。"""
        if not specs:
            raise AppError("至少填写一项变更")
        with self.database.immediate() as conn:
            event = self._own(conn, actor, event_id)
            if event.status != EventStatus.PUBLISHED:
                raise AppError("只有已发布的活动可以申请变更关键信息")
            if repo.pending_change(conn, event_id):
                raise AppError("已有待审核的变更申请")
            items = [
                self._normalize_spec(conn, event_id, spec) for spec in specs
            ]
            return repo.insert_change(
                conn, event.id, actor.id, note.strip(),
                format_time(self.clock.now()), items,
            )

    def review_change(self, actor, request_id: int, accept: bool, comment: str, confirmed: bool):
        """管理员审核变更。通过后写回并通知已报名用户。"""
        if actor.role.value != "平台管理员":
            raise AppError("无权限")
        if not confirmed:
            raise AppError("审核变更需要二次确认")
        with self.database.immediate() as conn:
            request = repo.get_change(conn, request_id)
            event = repo.get_event(conn, request.event_id)
            if actor.id == event.organizer_id:
                raise AppError("不能审核自己的活动")
            items = repo.change_items(conn, request.id)
            if accept:
                request.take_effect(
                    actor.id, comment, lambda: self._apply_items(conn, event.id, items)
                )
                repo.save_change(conn, request)
                self._notify_change(conn, event, request, items)
                self.audit.append(
                    conn, actor.id, "变更审核", "变更申请", request.id, "通过",
                    comment.strip(), event.id,
                )
            else:
                request.reject(actor.id, comment)
                repo.save_change(conn, request)
                self.audit.append(
                    conn, actor.id, "变更审核", "变更申请", request.id, "驳回",
                    request.review_comment, event.id,
                )
            return request

    def search(self, actor, keyword="", category="", city="", date_from="", date_to="",
               price_min=None, price_max=None, status="") -> list[dict]:
        """参与者组合查询。未发布和已取消不出现。"""
        if not actor.can_execute("browse"):
            raise AppError("无权限")
        try:
            if price_min not in (None, ""):
                float(price_min)
            if price_max not in (None, ""):
                float(price_max)
        except (TypeError, ValueError) as exc:
            raise AppError("价格区间必须是数字") from exc
        conn = self.database.connect()
        try:
            found = []
            now = self.clock.now()
            for event in repo.list_events(conn):
                if event.status not in _BROWSE_OK:
                    continue
                sessions = repo.sessions_of(conn, event.id)
                tickets = repo.tickets_of_event(conn, event.id)
                view = browse_status(event, sessions, now)
                if keyword and keyword.strip() not in event.title:
                    continue
                if category and category.strip() != event.category:
                    continue
                if city and city.strip() not in event.city:
                    continue
                if not _date_hit(sessions, date_from, date_to):
                    continue
                if not _price_hit(tickets, price_min, price_max):
                    continue
                if status and status != view:
                    continue
                prices = [ticket.price for ticket in tickets]
                found.append({
                    "id": event.id,
                    "title": event.title,
                    "category": event.category,
                    "city": event.city,
                    "intro": event.intro,
                    "need_review": event.need_review,
                    "status": event.status.value,
                    "browse_status": view,
                    "price_text": _price_text(prices),
                    "start_text": sessions[0].start_at if sessions else "",
                })
            return found
        finally:
            conn.close()

    def detail(self, actor, event_id: int) -> dict:
        """活动详情。参与者只能看已发布和已结束。"""
        conn = self.database.connect()
        try:
            event = repo.get_event(conn, event_id)
            self._visible(conn, actor, event)
            sessions = repo.sessions_of(conn, event.id)
            grouped = {
                session.id: repo.tickets_of(conn, session.id) for session in sessions
            }
            return {
                "event": event,
                "sessions": sessions,
                "tickets": grouped,
                "browse_status": browse_status(event, sessions, self.clock.now()),
            }
        finally:
            conn.close()

    def list_owned(self, actor) -> list[Event]:
        """组织者的活动。"""
        if not actor.can_execute("create_event"):
            raise AppError("无权限")
        conn = self.database.connect()
        try:
            return [
                event for event in repo.list_events(conn)
                if event.organizer_id == actor.id
            ]
        finally:
            conn.close()

    def list_by_status(self, actor, status: EventStatus) -> list[Event]:
        """管理员按状态查看。"""
        if actor.role.value != "平台管理员":
            raise AppError("无权限")
        conn = self.database.connect()
        try:
            return [
                event for event in repo.list_events(conn) if event.status == status
            ]
        finally:
            conn.close()

    def list_all(self, actor) -> list[Event]:
        """管理员查看全部活动。"""
        if actor.role.value != "平台管理员":
            raise AppError("无权限")
        conn = self.database.connect()
        try:
            return repo.list_events(conn)
        finally:
            conn.close()

    def changes_of(self, actor, event_id: int):
        """某个活动的变更申请。"""
        conn = self.database.connect()
        try:
            event = repo.get_event(conn, event_id)
            self._visible(conn, actor, event)
            if actor.role.value != "平台管理员" and event.organizer_id != actor.id:
                raise AppError("无权限")
            return [
                item for item in repo.list_changes(conn, None)
                if item.event_id == event_id
            ]
        finally:
            conn.close()

    def pending_changes(self, actor):
        """待审核变更。"""
        if actor.role.value != "平台管理员":
            raise AppError("无权限")
        conn = self.database.connect()
        try:
            return repo.list_changes(conn, ChangeStatus.PENDING.value)
        finally:
            conn.close()

    def change_items(self, actor, request_id: int):
        """查看变更项。审核结束前调用方仍应展示原值。"""
        conn = self.database.connect()
        try:
            request = repo.get_change(conn, request_id)
            event = repo.get_event(conn, request.event_id)
            if actor.role.value != "平台管理员" and event.organizer_id != actor.id:
                raise AppError("无权限")
            return repo.change_items(conn, request_id)
        finally:
            conn.close()

    def _own(self, conn, actor, event_id: int) -> Event:
        event = repo.get_event(conn, event_id)
        if not actor.can_execute("manage_event", event.organizer_id):
            raise AppError("无权限")
        return event

    @staticmethod
    def _require_reviewer(actor, event: Event) -> None:
        if actor.role.value != "平台管理员":
            raise AppError("无权限")
        if actor.id == event.organizer_id:
            raise AppError("不能审核自己的活动")

    @staticmethod
    def _require_editable(event: Event) -> None:
        if event.status not in (EventStatus.DRAFT, EventStatus.REJECTED):
            raise AppError("只有草稿或已驳回的活动可以修改场次和票种")

    def _visible(self, conn, actor, event: Event) -> None:
        if actor.role.value == "平台管理员" or event.organizer_id == actor.id:
            return
        if event.status in _BROWSE_OK:
            return
        grant = repo.find_grant(conn, event.id, actor.id)
        if grant is not None and grant.covers(event.id):
            return
        raise AppError("无权限查看该活动")

    def _assert_complete(self, conn, event: Event) -> None:
        if not (event.title and event.category and event.city and event.intro):
            raise AppError("活动信息不完整，不能提交")
        sessions = repo.sessions_of(conn, event.id)
        if not sessions:
            raise AppError("至少需要一个场次才能提交")
        for session in sessions:
            if session.capacity < 1:
                raise AppError("容量必须为正整数")
            ensure_time_order(session.deadline, session.start_at, session.end_at)
            tickets = repo.tickets_of(conn, session.id)
            if not tickets:
                raise AppError(f"场次「{session.name}」至少需要一个票种")
            names = [ticket.name for ticket in tickets]
            if len(names) != len(set(names)):
                raise AppError("同一场次票种名称不能重复")
            for ticket in tickets:
                ticket.set_price(ticket.price)

    def _normalize_spec(self, conn, event_id: int, spec) -> tuple:
        target_type, target_id, field, new_raw = spec
        if (target_type, field) not in _KEY_FIELDS:
            raise AppError("只能变更场次时间、场次容量或票种价格")
        if target_type == "场次":
            session = repo.get_session(conn, int(target_id))
            if session.event_id != event_id:
                raise AppError("场次不属于该活动")
            if field == "容量":
                seats = _capacity(new_raw)
                if seats < session.enrolled:
                    raise AppError("新容量不能小于已报名数")
                old, new = str(session.capacity), str(seats)
            else:
                new = format_time(parse_time(str(new_raw)))
                old = getattr(session, _TIME_ATTR[field])
            if old == new:
                raise AppError("新值与原值相同")
            return target_type, int(target_id), field, old, new
        ticket = repo.get_ticket(conn, int(target_id))
        session = repo.get_session(conn, ticket.session_id)
        if session.event_id != event_id:
            raise AppError("票种不属于该活动")
        price = _price(new_raw)
        old, new = f"{ticket.price:.2f}", f"{price:.2f}"
        if old == new:
            raise AppError("新值与原值相同")
        return "票种", ticket.id, "价格", old, new

    def _apply_items(self, conn, event_id: int, items) -> None:
        sessions = {}
        tickets = {}
        for item in items:
            if item.target_type == "场次":
                session = sessions.get(item.target_id)
                if session is None:
                    session = repo.get_session(conn, item.target_id)
                    sessions[item.target_id] = session
                if session.event_id != event_id:
                    raise AppError("变更项不属于该活动")
                if item.field == "容量":
                    seats = int(item.new_value)
                    if seats < session.enrolled:
                        raise AppError("新容量不能小于已报名数")
                    session.capacity = seats
                else:
                    setattr(session, _TIME_ATTR[item.field], item.new_value)
            else:
                ticket = tickets.get(item.target_id)
                if ticket is None:
                    ticket = repo.get_ticket(conn, item.target_id)
                    tickets[item.target_id] = ticket
                owner = repo.get_session(conn, ticket.session_id)
                if owner.event_id != event_id:
                    raise AppError("变更项不属于该活动")
                ticket.set_price(float(item.new_value))
        for session in sessions.values():
            ensure_time_order(session.deadline, session.start_at, session.end_at)
            repo.save_session(conn, session)
        for ticket in tickets.values():
            repo.save_ticket(conn, ticket)

    def _notify_change(self, conn, event, request, items) -> None:
        summary = "；".join(
            f"{item.field}由 {item.old_value} 改为 {item.new_value}" for item in items
        )
        receivers = repo.receivers_of_event(
            conn, event.id, ("待审核", "已通过", "候补中", "已签到")
        )
        for user_id in receivers:
            self.notify.add(
                conn, user_id, NoticeType.CHANGED, event.id, None,
                f"活动「{event.title}」关键信息已变更：{summary}",
                f"change:{request.id}:{user_id}",
            )

    @staticmethod
    def _fill_profile(event, title, category, city, intro, cover) -> None:
        if not title.strip() or not category.strip() or not city.strip():
            raise AppError("标题、分类和城市不能为空")
        event.title = title.strip()
        event.category = category.strip()
        event.city = city.strip()
        event.intro = intro.strip()
        event.cover = cover.strip()

    @staticmethod
    def _session_values(start_at, end_at, deadline, capacity):
        start = format_time(parse_time(start_at))
        end = format_time(parse_time(end_at))
        stop = format_time(parse_time(deadline))
        seats = _capacity(capacity)
        ensure_time_order(stop, start, end)
        return start, end, stop, seats

    @staticmethod
    def _new_ticket(session_id: int, name: str, price: float) -> TicketType:
        if not name.strip():
            raise AppError("票种名称不能为空")
        ticket = TicketType(
            id=0, session_id=session_id, name=name.strip(), price=0, is_free=True
        )
        ticket.set_price(price)
        return ticket


def browse_status(event: Event, sessions: list, now) -> str:
    """参与者看到的报名中、已满或已结束。"""
    if event.status == EventStatus.ENDED:
        return "已结束"
    if not sessions or all(parse_time(item.end_at) <= now for item in sessions):
        return "已结束"
    opening = [
        item for item in sessions
        if parse_time(item.deadline) >= now and parse_time(item.end_at) > now
    ]
    if not opening:
        return "已结束"
    if any(item.has_seat() for item in opening):
        return "报名中"
    return "已满"


def _date_hit(sessions, date_from: str, date_to: str) -> bool:
    if not date_from and not date_to:
        return True
    start = _bound(date_from, False)
    end = _bound(date_to, True)
    for session in sessions:
        if start and session.start_at < start:
            continue
        if end and session.start_at > end:
            continue
        return True
    return False


def _bound(text: str, is_end: bool):
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    if len(raw) == 10:
        raw = raw + (" 23:59:59" if is_end else " 00:00:00")
    return format_time(parse_time(raw))


def _price_hit(tickets, price_min, price_max) -> bool:
    if price_min is None and price_max is None:
        return True
    if not tickets:
        return False
    low = None if price_min in (None, "") else float(price_min)
    high = None if price_max in (None, "") else float(price_max)
    for ticket in tickets:
        if low is not None and ticket.price < low:
            continue
        if high is not None and ticket.price > high:
            continue
        return True
    return False


def _price_text(prices: list[float]) -> str:
    if not prices:
        return "暂无票种"
    low, high = min(prices), max(prices)
    if high == 0:
        return "免费"
    if low == high:
        return f"{low:.2f} 元"
    return f"{low:.2f}-{high:.2f} 元"


def _capacity(value) -> int:
    raw = str(value).strip()
    if not raw.isdigit() or int(raw) < 1:
        raise AppError("容量必须为正整数")
    return int(raw)


def _price(value) -> float:
    try:
        number = round(float(str(value).strip()), 2)
    except ValueError as exc:
        raise AppError("价格必须是数字") from exc
    if number < 0:
        raise AppError("价格不能为负")
    return number
