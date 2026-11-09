# -*- coding: utf-8 -*-
"""活动汇界面。版式和用词按实验二的页面，数据走原来的业务包。"""
# pylint: disable=line-too-long,missing-function-docstring,invalid-name,arguments-differ,unused-argument

from __future__ import annotations

import html
import secrets
import threading
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from ticketapp import repo
from ticketapp.errors import AppError
from ticketapp.models import EventStatus, Role, mask_phone
from ticketapp.system import System

STATIC = Path(__file__).resolve().parent / "webstatic" / "site.css"
COVERS = ("#8c3a32", "#1c6a61", "#243044", "#6b4a2a", "#3d4f3a")
_SESSIONS: dict[str, dict] = {}
_LOCK = threading.Lock()


def esc(value) -> str:
    """放进 HTML 之前转义。"""
    return html.escape("" if value is None else str(value), quote=True)


def pill(text: str, kind: str = "") -> str:
    """状态胶囊，颜色和实验二一致。"""
    return f'<span class="pill {kind}">{esc(text)}</span>'


def status_kind(text: str) -> str:
    """把业务状态映射到页面上的颜色。"""
    if text in {"已发布", "已通过", "已签到", "报名中", "可报名"}:
        return "ok"
    if text in {"待审核", "候补中", "已满", "待支付", "已满，可候补"}:
        return "wait"
    if text in {"已驳回", "已取消", "已失效", "已缺席", "已下架", "重复签到"}:
        return "bad"
    return ""


class HubHandler(BaseHTTPRequestHandler):
    """活动汇的页面。每个请求自己找当前用户。"""

    system: System

    def do_GET(self) -> None:  # noqa: N802
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._route("POST")

    def log_message(self, fmt: str, *args) -> None:
        return

    def _route(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/site.css":
                self._css()
                return
            user = self._user()
            if path in {"/", "/login"} and method == "GET":
                self._login_page(_q(query, "err"))
                return
            if path == "/login" and method == "POST":
                self._login()
                return
            if path == "/logout":
                self._logout()
                return
            if user is None:
                self._redirect("/login")
                return
            self._dispatch(method, path, query, user)
        except AppError as exc:
            self._flash_back(str(exc))

    def _dispatch(self, method: str, path: str, query: dict, user) -> None:
        if path == "/discover":
            self._discover(user, query)
        elif path == "/event":
            self._event(user, query)
        elif path == "/confirm":
            self._confirm(user, query)
        elif path == "/register" and method == "POST":
            self._register(user)
        elif path == "/result":
            self._result(user)
        elif path == "/mine":
            self._mine(user)
        elif path == "/cancel-reg" and method == "POST":
            self._cancel_reg(user)
        elif path == "/notices":
            self._notices(user)
        elif path == "/read" and method == "POST":
            self._read(user)
        elif path == "/org":
            self._org_list(user)
        elif path == "/org/edit":
            self._org_edit(user, query)
        elif path == "/org/save" and method == "POST":
            self._org_save(user)
        elif path == "/org/session" and method == "POST":
            self._org_session(user)
        elif path == "/org/ticket" and method == "POST":
            self._org_ticket(user)
        elif path == "/org/submit" and method == "POST":
            self._org_submit(user)
        elif path == "/org/cancel":
            self._org_cancel_page(user, query)
        elif path == "/org/cancel-do" and method == "POST":
            self._org_cancel(user)
        elif path == "/org/roster":
            self._roster(user, query)
        elif path == "/org/review" and method == "POST":
            self._review_reg(user)
        elif path == "/org/promote" and method == "POST":
            self._promote(user)
        elif path == "/org/pay" and method == "POST":
            self._pay(user)
        elif path == "/org/grant" and method == "POST":
            self._grant(user)
        elif path == "/org/export" and method == "POST":
            self._export(user)
        elif path == "/org/change":
            self._change_page(user, query)
        elif path == "/org/change-do" and method == "POST":
            self._change(user)
        elif path == "/admin":
            self._admin_events(user)
        elif path == "/admin/approve" and method == "POST":
            self._admin_approve(user)
        elif path == "/admin/reject" and method == "POST":
            self._admin_reject(user)
        elif path == "/admin/offline" and method == "POST":
            self._admin_offline(user)
        elif path == "/admin/changes":
            self._admin_changes(user)
        elif path == "/admin/change" and method == "POST":
            self._admin_change(user)
        elif path == "/admin/users":
            self._admin_users(user)
        elif path == "/admin/user" and method == "POST":
            self._admin_user(user)
        elif path == "/logs":
            self._logs(user, query)
        elif path == "/checkin" and method == "POST":
            self._checkin(user)
        elif path == "/checkin":
            self._checkin_page(user, query)
        else:
            self._redirect(self._home(user))

    def _login_page(self, error: str) -> None:
        warn = f'<div class="note bad" style="margin-top:12px">{esc(error)}</div>' if error else ""
        body = f"""
<div class="login">
  <section class="hero">
    <div class="brand"><span class="mark">汇</span>活动汇</div>
    <h1>把活动发布、报名、<br>候补和现场核销放在一处。</h1>
    <p>面向校园和社团活动。收费票本期只记录支付状态，不接入真实支付。通知只做站内记录。</p>
    <div class="roles">
      <div><b>参与者</b><span>查询活动、报名、取消、看通知。从详情到完成不超过 3 步。</span></div>
      <div><b>组织者</b><span>创建活动、管场次票种、审核报名、导出名单。不能审核自己的活动。</span></div>
      <div><b>检票人员</b><span>只能核销被授权的活动，不能导出，也不能看其他活动。</span></div>
      <div><b>平台管理员</b><span>审核、下架、强制取消、管用户，并查询全部日志。</span></div>
    </div>
  </section>
  <section class="login-form">
    <form class="card login-card" method="post" action="/login">
      <h2>登录</h2>
      <p class="sub">登录后按账号角色进入对应工作台。未登录不能报名、核销或导出。</p>
      <div class="stack">
        <label class="field"><span>手机号或用户名</span><input name="username" value="linxiao"></label>
        <label class="field"><span>密码</span><input name="password" type="password" value="123456"></label>
        <button class="btn primary" type="submit">登录</button>
        {warn}
        <p class="tiny">演示密码都是 123456。参与者 linxiao / zhou / chen，组织者 organizer，检票 checker，管理员 admin。越权请求会被拒绝。敏感操作进入业务页后还要二次确认。</p>
      </div>
    </form>
  </section>
</div>"""
        self._html("登录 · 活动汇", body, bare=True)

    def _login(self) -> None:
        form = self._form()
        user = self.system.users.login(form.get("username", ""), form.get("password", ""))
        sid = secrets.token_hex(16)
        with _LOCK:
            _SESSIONS[sid] = {"user_id": user.id}
        self.send_response(303)
        self.send_header("Set-Cookie", f"sid={sid}; HttpOnly; Path=/")
        self.send_header("Location", self._home(user))
        self.end_headers()

    def _logout(self) -> None:
        sid = self._sid()
        with _LOCK:
            _SESSIONS.pop(sid, None)
        self.send_response(303)
        self.send_header("Set-Cookie", "sid=; Max-Age=0; Path=/")
        self.send_header("Location", "/login")
        self.end_headers()

    def _discover(self, user, query) -> None:
        rows = self.system.events.search(
            user,
            keyword=_q(query, "keyword"),
            category=_q(query, "category"),
            city=_q(query, "city"),
            date_from=_q(query, "date_from"),
            date_to=_q(query, "date_to"),
            price_min=_q(query, "price_min") or None,
            price_max=_q(query, "price_max") or None,
            status=_q(query, "status"),
        )
        cards = []
        for row in rows:
            color = COVERS[row["id"] % len(COVERS)]
            review = "需审核" if row["need_review"] else "报名即通过"
            kind = status_kind(row["browse_status"])
            cards.append(f"""
<a class="card event" href="/event?id={row['id']}">
  <div class="cover" style="background:{color}"><span>{esc(row['price_text'])}</span><b>{esc(row['title'])}</b></div>
  <div class="meta">
    <p>{esc(row['category'])} · {esc(row['city'])}<br>{esc(row['intro'][:42])}</p>
    <div class="pills">{pill(row['browse_status'], kind)}{pill(review)}</div>
  </div>
</a>""")
        empty = '<p class="tiny">没有同时满足全部条件的活动。未发布、已下架、已取消不会出现在这里。</p>'
        body = f"""
{self._top(user, "发现活动")}
<div class="page">
  <div class="page-head"><div><h1>发现活动</h1>
  <p class="sub">只展示已发布活动。未发布、已下架、已取消不会出现在这里。</p></div></div>
  <form class="card filters" method="get" action="/discover">
    <label class="field grow"><span>关键词</span><input name="keyword" value="{esc(_q(query,'keyword'))}"></label>
    <label class="field"><span>分类</span><input name="category" value="{esc(_q(query,'category'))}" placeholder="文艺"></label>
    <label class="field"><span>城市</span><input name="city" value="{esc(_q(query,'city'))}" placeholder="南京"></label>
    <label class="field"><span>开始日期</span><input name="date_from" value="{esc(_q(query,'date_from'))}" placeholder="2026-11-01"></label>
    <label class="field"><span>结束日期</span><input name="date_to" value="{esc(_q(query,'date_to'))}" placeholder="2026-11-30"></label>
    <label class="field"><span>状态</span>
      <select name="status">
        <option value="">全部</option>
        {self._options(["报名中", "已满", "已结束"], _q(query, "status"))}
      </select></label>
    <button class="btn primary" type="submit">查询</button>
  </form>
  <div class="grid3">{''.join(cards) if cards else ''}</div>
  {'' if cards else empty}
</div>"""
        self._html("发现活动 · 活动汇", body)

    def _event(self, user, query) -> None:
        event_id = int(_q(query, "id") or "0")
        data = self.system.events.detail(user, event_id)
        event = data["event"]
        chosen_session = int(_q(query, "session") or "0")
        chosen_ticket = int(_q(query, "ticket") or "0")
        sessions_html = []
        ticket_html = []
        note = "提交时以服务器当时的余量为准，不采用打开页面时的旧数字。"
        selected = None
        for session in data["sessions"]:
            closed = self._session_closed(session)
            on = " on" if session.id == chosen_session else ""
            if closed:
                badge = '<button class="btn tiny off" disabled>已截止</button>'
            elif session.has_seat():
                badge = pill("可报名", "ok")
            else:
                badge = pill("已满，可候补", "wait")
            sessions_html.append(f"""
<a class="session{on}" href="/event?id={event.id}&session={session.id}">
  <div><b>{esc(session.name)}</b>
  <p class="tiny">{esc(session.start_at)} · {esc(session.place)}<br>
  截止 {esc(session.deadline)} · 容量 {session.capacity} · 已报名 {session.enrolled} · 剩余 {session.remaining()} · 候补 {session.waitlist}</p></div>
  {badge}
</a>""")
            if session.id == chosen_session:
                selected = session
                for ticket in data["tickets"].get(session.id, []):
                    mark = " on" if ticket.id == chosen_ticket else ""
                    ticket_html.append(
                        f'<a class="session{mark}" href="/event?id={event.id}&session={session.id}&ticket={ticket.id}">'
                        f'<div><b>{esc(ticket.name)}</b><p class="tiny">{esc(ticket.charge_label())}</p></div>'
                        f'{pill("已选", "hot") if ticket.id == chosen_ticket else ""}</a>'
                    )
                if closed:
                    note = "该场次已截止，不能报名，也不能再取消。"
                elif not session.has_seat():
                    note = "该场次已满。继续提交会进入候补，按进入候补的时间排队，不占用已报名数。"
        next_btn = ""
        if user.role == Role.PARTICIPANT and chosen_session and chosen_ticket and selected:
            next_btn = (
                f'<a class="btn primary" style="display:block;text-align:center;line-height:42px;height:42px;margin-top:16px"'
                f' href="/confirm?session={chosen_session}&ticket={chosen_ticket}">下一步：确认报名</a>'
            )
        title_name = selected.name if selected else "先选择场次"
        body = f"""
{self._top(user, "发现活动")}
<div class="page">
  {self._steps(1)}
  <div class="layout">
    <section class="card block">
      <div class="pills">{pill(event.status.value, status_kind(event.status.value))}{pill(event.category)}{pill(event.city)}</div>
      <h1 style="margin-top:10px">{esc(event.title)}</h1>
      <p class="sub">{esc(event.intro)}</p>
      <h3 style="margin-top:16px">选择场次</h3>
      {''.join(sessions_html)}
    </section>
    <aside class="card block">
      <h3>{esc(title_name)} · 选择票种</h3>
      {''.join(ticket_html) or '<p class="tiny">从左侧选择一个场次。</p>'}
      <div class="note" style="margin-top:14px">{esc(note)}</div>
      {next_btn}
    </aside>
  </div>
</div>"""
        self._html(event.title + " · 活动汇", body)

    def _confirm(self, user, query) -> None:
        if user.role != Role.PARTICIPANT:
            raise AppError("只有参与者可以报名")
        session_id = int(_q(query, "session") or "0")
        ticket_id = int(_q(query, "ticket") or "0")
        info = self._ticket_view(user, session_id, ticket_id)
        seat = f"剩余 {info['session'].remaining()}，候补 {info['session'].waitlist} 人"
        body = f"""
{self._top(user, "发现活动")}
<div class="page">
  {self._steps(2)}
  <div style="width:720px;margin:10px auto 0">
    <section class="card block">
      <h1>确认报名</h1>
      <p class="sub">这是第 2 步。提交后直接看到结果，全程 3 步。</p>
      <div class="kvs" style="margin-top:16px">
        <i>活动</i><b>{esc(info['event'].title)}</b>
        <i>场次</i><b>{esc(info['session'].name)} · {esc(info['session'].start_at)}</b>
        <i>票种</i><b>{esc(info['ticket'].name)} · {esc(info['ticket'].charge_label())}</b>
        <i>报名人</i><b>{esc(user.username)} · {esc(mask_phone(user.phone))}</b>
        <i>当前余量</i><b>{esc(seat)}</b>
      </div>
      <div class="note" style="margin-top:16px">点提交时会重新检查：活动是否仍发布、是否过了截止、你是否已经有一条有效报名、场次是否还有余量。上面的余量只是打开这一页时的数字。</div>
      <form class="row" style="margin-top:18px" method="post" action="/register">
        <input type="hidden" name="session_id" value="{session_id}">
        <input type="hidden" name="ticket_id" value="{ticket_id}">
        <a class="btn" href="/event?id={info['event'].id}&session={session_id}&ticket={ticket_id}">返回修改</a>
        <button class="btn primary" type="submit">提交报名</button>
      </form>
    </section>
  </div>
</div>"""
        self._html("确认报名 · 活动汇", body)

    def _register(self, user) -> None:
        form = self._form()
        record = self.system.regs.register(
            user, int(form["session_id"]), int(form["ticket_id"])
        )
        info = self._ticket_view(user, record.session_id, record.ticket_id)
        self._box()["result"] = {
            "status": record.status.value,
            "code": record.code,
            "title": info["event"].title,
            "session": info["session"].name,
            "enrolled": info["session"].enrolled,
            "capacity": info["session"].capacity,
            "payment": record.payment.value if record.payment else "免费票不记支付状态",
        }
        self._redirect("/result")

    def _result(self, user) -> None:
        result = self._box().get("result")
        if not result:
            self._redirect("/mine")
            return
        kind = status_kind(result["status"])
        headline = {
            "已通过": "报名已通过",
            "待审核": "已提交，等待审核",
            "候补中": "已进入候补",
        }.get(result["status"], result["status"])
        body = f"""
{self._top(user, "发现活动")}
<div class="page">
  {self._steps(3)}
  <div style="width:720px;margin:10px auto 0">
    <section class="card block">
      {pill(result['status'], kind)}
      <h1 style="margin-top:10px">{esc(headline)}</h1>
      <p class="sub">报名号 {esc(result['code'])}。{esc(result['title'])} · {esc(result['session'])}</p>
      <div class="kvs" style="margin-top:16px">
        <i>已报名数</i><b>{result['enrolled']} / {result['capacity']}</b>
        <i>支付状态</i><b>{esc(result['payment'])}</b>
        <i>若有人取消</i><b>候补按时间自动递补，并写一条站内通知</b>
      </div>
      <h3 style="margin-top:18px">如果这次不能报名，结果页会直接写原因</h3>
      <div class="note bad" style="margin-top:8px">已报名：你在该场次已有待审核、已通过或候补中的记录。</div>
      <div class="note bad" style="margin-top:8px">已截止：超过场次报名截止时间，不能新报名，也不能再取消。</div>
      <a class="btn primary" style="display:inline-block;margin-top:16px;line-height:36px" href="/mine">查看我的报名</a>
    </section>
  </div>
</div>"""
        self._html("报名结果 · 活动汇", body)

    def _mine(self, user) -> None:
        rows = []
        now = self.system.clock.now().strftime("%Y-%m-%d %H:%M:%S")
        for row in self.system.regs.list_mine(user):
            can_cancel = row["status"] in {"待审核", "已通过", "候补中"} and row["deadline"] >= now
            if can_cancel:
                action = (
                    f'<form method="post" action="/cancel-reg"><input type="hidden" name="id" value="{row["id"]}">'
                    f'<button class="btn tiny" type="submit">取消报名</button></form>'
                )
            elif row["status"] in {"已签到", "已取消", "已失效", "已缺席"}:
                action = '<span class="tiny">终态，不能再改</span>'
            else:
                action = '<span class="tiny">截止后不可取消</span>'
            pay = row["payment_status"] or "免费，无支付状态"
            rows.append(
                "<tr>"
                f'<td class="num">{esc(row["code"])}</td>'
                f'<td>{esc(row["event_title"])} · {esc(row["session_name"])}<br><span class="tiny">截止 {esc(row["deadline"])}</span></td>'
                f'<td>{esc(row["ticket_name"])}</td>'
                f'<td>{pill(row["status"], status_kind(row["status"]))}</td>'
                f'<td class="tiny">{esc(pay)}</td><td>{action}</td></tr>'
            )
        body = f"""
{self._top(user, "我的报名")}
<div class="page">
  <div class="page-head"><div><h1>我的报名</h1>
  <p class="sub">有效报名是待审核、已通过、候补中。已取消或已失效后可以重新报名。截止后取消按钮关闭。</p></div></div>
  {self._banner()}
  <section class="card"><table>
    <thead><tr><th>报名号</th><th>活动 / 场次</th><th>票种</th><th>状态</th><th>支付</th><th>操作</th></tr></thead>
    <tbody>{''.join(rows) or '<tr><td colspan="6" class="tiny">还没有报名。</td></tr>'}</tbody>
  </table></section>
</div>"""
        self._html("我的报名 · 活动汇", body)

    def _cancel_reg(self, user) -> None:
        self.system.regs.cancel(user, int(self._form()["id"]))
        self._remember("已取消。要再参加需要重新报名。")
        self._redirect("/mine")

    def _notices(self, user) -> None:
        items = []
        for notice in self.system.notify.list_mine(user):
            dot = "unread" if not notice.read_at else "read"
            button = ""
            if not notice.read_at:
                button = (
                    f'<form method="post" action="/read"><input type="hidden" name="id" value="{notice.id}">'
                    f'<button class="btn tiny" type="submit">标为已读</button></form>'
                )
            items.append(
                f'<div class="notice"><i class="{dot}"></i><div><b>{esc(notice.ntype.value)}</b>'
                f'<p>{esc(notice.content)}</p></div><div class="tiny">{esc(notice.created_at)}{button}</div></div>'
            )
        body = f"""
{self._top(user, "通知")}
<div class="page">
  <div class="page-head"><div><h1>通知</h1>
  <p class="sub">只有审核结果、递补成功、活动取消、关键信息变更。不发短信，不做推送。</p></div></div>
  <section class="card list">{''.join(items) or '<p class="tiny" style="padding:16px">还没有通知。</p>'}</section>
</div>"""
        self._html("通知 · 活动汇", body)

    def _read(self, user) -> None:
        self.system.notify.mark_read(user, int(self._form()["id"]))
        self._redirect("/notices")

    def _org_list(self, user) -> None:
        self._need(user, Role.ORGANIZER)
        rows = []
        for event in self.system.events.list_owned(user):
            detail = self.system.events.detail(user, event.id)
            review = "需审核" if event.need_review else "报名即通过"
            actions = f'<a class="btn tiny" href="/org/edit?id={event.id}">打开</a>'
            if event.status == EventStatus.PUBLISHED:
                actions += (
                    f' <a class="btn tiny" href="/org/roster?id={event.id}">名单</a>'
                    f' <a class="btn tiny" href="/org/change?id={event.id}">变更</a>'
                    f' <a class="btn tiny danger" href="/org/cancel?id={event.id}">取消活动</a>'
                )
            reason = f'<br><span class="tiny">{esc(event.reject_reason)}</span>' if event.reject_reason else ""
            rows.append(
                "<tr>"
                f"<td>{esc(event.title)}<br><span class=\"tiny\">{esc(event.city)} · {esc(event.category)}</span>{reason}</td>"
                f"<td>{pill(event.status.value, status_kind(event.status.value))}</td>"
                f"<td>{review}</td><td class=\"num\">{len(detail['sessions'])}</td><td>{actions}</td></tr>"
            )
        body = f"""
{self._side(user, "我的活动", [("我的活动", "/org"), ("新建活动", "/org/edit"), ("操作日志", "/logs")])}
<main class="main">
  <div class="page-head"><div><h1>我的活动</h1>
  <p class="sub">一个活动只有一个组织者。审核期间参与者看不见。驳回原因会留在活动上，改完可以再提交。</p></div>
  <a class="btn primary" href="/org/edit">新建活动</a></div>
  {self._banner()}
  <section class="card"><table>
    <thead><tr><th>活动</th><th>状态</th><th>报名审核</th><th>场次</th><th>操作</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></section>
  <p class="tiny" style="margin-top:12px">已发布活动可以直接改介绍。场次时间、价格、容量必须走变更申请。取消活动会二次确认。</p>
</main></div>"""
        self._html("我的活动 · 活动汇", body, shell=True)

    def _org_edit(self, user, query) -> None:
        self._need(user, Role.ORGANIZER)
        event_id = int(_q(query, "id") or "0")
        event = None
        sessions = ""
        if event_id:
            data = self.system.events.detail(user, event_id)
            event = data["event"]
            blocks = []
            for session in data["sessions"]:
                tickets = "、".join(
                    f"{ticket.name} {ticket.charge_label()}"
                    for ticket in data["tickets"].get(session.id, [])
                )
                blocks.append(
                    f'<div class="session"><div><b>{esc(session.name)}</b> · 编号 {session.id}'
                    f'<p class="tiny">{esc(session.place)} · {esc(session.start_at)} 至 {esc(session.end_at)}'
                    f'<br>截止 {esc(session.deadline)} · 容量 {session.capacity}<br>{esc(tickets or "还没有票种")}</p></div></div>'
                )
            sessions = "".join(blocks)
        title = event.title if event else ""
        category = event.category if event else "文艺"
        city = event.city if event else "南京"
        intro = event.intro if event else ""
        need = "1" if event and event.need_review else "0"
        heading = "编辑活动" if event else "新建活动"
        body = f"""
{self._side(user, "新建活动", [("我的活动", "/org"), ("新建活动", "/org/edit"), ("操作日志", "/logs")])}
<main class="main">
  <div class="page-head"><div><h1>{heading}</h1>
  <p class="sub">基本信息、至少一个场次、每个场次至少一个票种，才允许提交审核。</p></div></div>
  {self._banner()}
  <div class="split">
    <section class="card block">
      <form method="post" action="/org/save">
        <input type="hidden" name="id" value="{event_id}">
        <div class="form-grid">
          <label class="field"><span>活动名称</span><input name="title" value="{esc(title)}"></label>
          <label class="field"><span>分类</span><input name="category" value="{esc(category)}"></label>
          <label class="field"><span>城市</span><input name="city" value="{esc(city)}"></label>
          <label class="field"><span>报名是否需要审核</span>
            <select name="need_review">{self._options_pairs([("0", "报名即通过"), ("1", "需要组织者审核")], need)}</select></label>
          <label class="field full"><span>介绍</span><textarea name="intro" rows="3">{esc(intro)}</textarea></label>
        </div>
        <div class="row" style="margin-top:12px">
          <button class="btn" type="submit">保存资料</button>
        </div>
      </form>
      <h3 style="margin-top:16px">场次与票种</h3>
      {sessions or '<p class="tiny">保存活动后再添加场次。容量记在场次上，不记在票种上。</p>'}
      {self._session_form(event_id) if event and event.status in (EventStatus.DRAFT, EventStatus.REJECTED) else ''}
      {'' if not event or event.status in (EventStatus.DRAFT, EventStatus.REJECTED) else '<p class="tiny">已发布后不能直接改场次和票种。时间、价格、容量请走变更申请。</p>'}
      <p class="tiny" style="margin-top:8px">容量必须是正整数，价格不能为负，同一场次票种名称不能重复。已发布后，时间和容量要走变更申请。</p>
    </section>
    <aside class="card block">
      <h3>提交前检查</h3>
      <p class="tiny">信息完整后进入待审核。平台管理员通过后自动发布。管理员不能在审核时替你改票价和场次。</p>
      <div class="note" style="margin-top:12px">你不能审核自己创建的活动。通过、驳回只出现在管理员的审核台。</div>
      {self._submit_form(event_id) if event and event.status in (EventStatus.DRAFT, EventStatus.REJECTED) else ''}
    </aside>
  </div>
</main></div>"""
        self._html(heading + " · 活动汇", body, shell=True)

    def _session_form(self, event_id: int) -> str:
        return f"""
<form method="post" action="/org/session" style="margin-top:12px">
  <input type="hidden" name="event_id" value="{event_id}">
  <div class="form-grid">
    <label class="field"><span>场次名称</span><input name="name" value="第一场"></label>
    <label class="field"><span>地点</span><input name="place" placeholder="仙林大礼堂"></label>
    <label class="field"><span>开始</span><input name="start" placeholder="2026-11-10 19:00"></label>
    <label class="field"><span>结束</span><input name="end" placeholder="2026-11-10 21:00"></label>
    <label class="field"><span>报名截止</span><input name="deadline" placeholder="2026-11-10 12:00"></label>
    <label class="field"><span>场次容量</span><input name="capacity" value="80"></label>
  </div>
  <button class="btn" style="margin-top:8px" type="submit">添加场次</button>
</form>
<form method="post" action="/org/ticket" class="row" style="margin-top:8px">
  <input type="hidden" name="event_id" value="{event_id}">
  <input name="session_id" placeholder="场次编号" style="width:90px">
  <input name="name" placeholder="票种名称" style="width:120px">
  <input name="price" placeholder="价格，0 为免费" style="width:140px">
  <button class="btn" type="submit">添加票种</button>
</form>"""

    def _submit_form(self, event_id: int) -> str:
        return (
            f'<form method="post" action="/org/submit" style="margin-top:16px">'
            f'<input type="hidden" name="id" value="{event_id}">'
            f'<button class="btn primary" type="submit">提交审核</button></form>'
        )

    def _org_save(self, user) -> None:
        self._need(user, Role.ORGANIZER)
        form = self._form()
        need = form.get("need_review") == "1"
        event_id = int(form.get("id") or "0")
        if event_id:
            self.system.events.update_profile(
                user, event_id, form.get("title", ""), form.get("category", ""),
                form.get("city", ""), form.get("intro", ""), "", need,
            )
        else:
            created = self.system.events.create_event(
                user, form.get("title", ""), form.get("category", ""),
                form.get("city", ""), form.get("intro", ""), "", need,
            )
            event_id = created.id
        self._remember("资料已保存。")
        self._redirect(f"/org/edit?id={event_id}")

    def _org_session(self, user) -> None:
        self._need(user, Role.ORGANIZER)
        form = self._form()
        self.system.events.add_session(
            user, int(form["event_id"]), form.get("name", ""), form.get("place", ""),
            form.get("start", ""), form.get("end", ""), form.get("deadline", ""),
            form.get("capacity", ""),
        )
        self._redirect(f"/org/edit?id={form['event_id']}")

    def _org_ticket(self, user) -> None:
        self._need(user, Role.ORGANIZER)
        form = self._form()
        self.system.events.add_ticket(
            user, int(form["session_id"]), form.get("name", ""), float(form.get("price") or "0")
        )
        self._redirect(f"/org/edit?id={form['event_id']}")

    def _org_submit(self, user) -> None:
        self._need(user, Role.ORGANIZER)
        event_id = int(self._form()["id"])
        self.system.events.submit(user, event_id)
        self._remember("已提交审核。审核期间参与者看不见。")
        self._redirect("/org")

    def _org_cancel_page(self, user, query) -> None:
        self._need(user, Role.ORGANIZER)
        event_id = int(_q(query, "id") or "0")
        event = self.system.events.detail(user, event_id)["event"]
        body = f"""
{self._side(user, "我的活动", [("我的活动", "/org"), ("新建活动", "/org/edit")])}
<main class="main">
  <section class="card modal" style="max-width:480px">
    <h2>取消活动</h2>
    <p class="sub">{esc(event.title)}。有效报名会变成已失效，候补清空，收费票标记待退款。已签到记录保留。</p>
    <form method="post" action="/org/cancel-do">
      <input type="hidden" name="id" value="{event.id}">
      <label class="field" style="margin-top:12px"><span>取消原因</span><textarea name="reason" rows="3"></textarea></label>
      <div class="row" style="margin-top:14px">
        <a class="btn" href="/org">返回</a>
        <button class="btn danger" type="submit">确认取消</button>
      </div>
    </form>
  </section>
</main></div>"""
        self._html("取消活动 · 活动汇", body, shell=True)

    def _org_cancel(self, user) -> None:
        form = self._form()
        if not form.get("reason", "").strip():
            raise AppError("取消活动需要填写原因")
        self.system.events.cancel_event(user, int(form["id"]), True, form.get("reason", ""))
        self._remember("活动已取消。")
        self._redirect("/admin" if user.role == Role.ADMIN else "/org")

    def _roster(self, user, query) -> None:
        self._need(user, Role.ORGANIZER)
        event_id = int(_q(query, "id") or "0")
        event = self.system.events.detail(user, event_id)["event"]
        summary = self.system.stats.summary(user, event_id)
        stats = []
        ticket_lines = []
        for item in summary["sessions"]:
            rate = f"{item['rate']:.0%}"
            stats.append(
                f'<div class="card stat"><span>{esc(item["name"])} 容量</span><b>{item["capacity"]}</b></div>'
                f'<div class="card stat"><span>已报名</span><b>{item["enrolled"]}</b></div>'
                f'<div class="card stat"><span>剩余</span><b>{item["remaining"]}</b></div>'
                f'<div class="card stat"><span>候补</span><b>{item["waitlist"]}</b></div>'
                f'<div class="card stat"><span>已签到</span><b>{item["checked"]}</b></div>'
                f'<div class="card stat"><span>签到率</span><b>{rate}</b></div>'
            )
            bits = " · ".join(f"{name} {count} 人" for name, count in item["tickets"])
            ticket_lines.append(f"<p class=\"tiny\">{esc(item['name'])}：{esc(bits or '暂无')}</p>")
        people = []
        for row in self.system.stats.roster(user, event_id):
            buttons = []
            if row["status"] == "待审核":
                buttons.append(self._post_button("/org/review", {"id": row["id"], "accept": "1", "event_id": event_id}, "通过"))
                buttons.append(
                    f'<form method="post" action="/org/review" style="display:inline">'
                    f'<input type="hidden" name="id" value="{row["id"]}"><input type="hidden" name="accept" value="0">'
                    f'<input type="hidden" name="event_id" value="{event_id}">'
                    f'<input name="reason" placeholder="拒绝原因" style="width:110px;height:28px">'
                    f'<button class="btn tiny danger" type="submit">拒绝</button></form>'
                )
            if row["status"] == "候补中":
                buttons.append(self._post_button("/org/promote", {"id": row["id"], "event_id": event_id}, "手动递补"))
            if row["payment"] == "待支付":
                buttons.append(self._post_button("/org/pay", {"id": row["id"], "event_id": event_id}, "标记已支付"))
            pay = row["payment"] or "免费"
            people.append(
                "<tr>"
                f'<td class="num">{esc(row["code"])}</td><td>{esc(row["username"])}</td>'
                f'<td class="num">{esc(row["phone"])}</td><td>{esc(row["ticket"])}</td>'
                f'<td>{pill(row["status"], status_kind(row["status"]))}</td>'
                f'<td class="tiny">{esc(pay)}</td><td>{"".join(buttons)}</td></tr>'
            )
        body = f"""
{self._side(user, "报名名单", self._org_links(event_id))}
<main class="main">
  <div class="page-head"><div><h1>报名名单 · {esc(event.title)}</h1>
  <p class="sub">统计按场次。导出包含脱敏手机号，并记一条操作日志。检票人员没有这个按钮。</p></div>
  <form method="post" action="/org/export"><input type="hidden" name="id" value="{event_id}">
  <button class="btn primary" type="submit">导出名单</button></form></div>
  {self._banner()}
  <div class="stats">{''.join(stats)}</div>
  <div class="split">
    <section class="card"><table>
      <thead><tr><th>报名号</th><th>用户</th><th>手机号</th><th>票种</th><th>状态</th><th>支付</th><th></th></tr></thead>
      <tbody>{''.join(people) or '<tr><td colspan="7" class="tiny">还没有报名。</td></tr>'}</tbody>
    </table></section>
    <aside>
      <div class="card block"><h3>按票种</h3>{''.join(ticket_lines)}
      <p class="tiny">待审核不计入已报名。手动递补不能插到更早的候补前面。</p></div>
      <div class="card block" style="margin-top:12px">
        <h3>本活动检票人员</h3>
        <form method="post" action="/org/grant">
          <input type="hidden" name="event_id" value="{event_id}">
          <label class="field"><span>用户名</span><input name="username" placeholder="checker 或某个参与者"></label>
          <button class="btn" style="margin-top:8px" type="submit">指定检票人员</button>
        </form>
        <p class="tiny" style="margin-top:8px">没有这张授权就不能核销。组织者也可以把检票权授给参与者账号。</p>
      </div>
    </aside>
  </div>
</main></div>"""
        self._html("报名名单 · 活动汇", body, shell=True)

    def _review_reg(self, user) -> None:
        form = self._form()
        self.system.regs.review(user, int(form["id"]), form.get("accept") == "1", form.get("reason", ""))
        self._redirect(f"/org/roster?id={form['event_id']}")

    def _promote(self, user) -> None:
        form = self._form()
        self.system.regs.promote_manual(user, int(form["id"]))
        self._redirect(f"/org/roster?id={form['event_id']}")

    def _pay(self, user) -> None:
        form = self._form()
        self.system.regs.mark_paid(user, int(form["id"]), True)
        self._redirect(f"/org/roster?id={form['event_id']}")

    def _grant(self, user) -> None:
        form = self._form()
        name = form.get("username", "").strip()
        conn = self.system.database.connect()
        try:
            target = repo.get_user_by_name(conn, name)
        finally:
            conn.close()
        if target is None:
            raise AppError("找不到这个用户")
        self.system.users.grant_checker(user, int(form["event_id"]), target.id)
        self._remember(f"已授权 {name} 核销本活动。")
        self._redirect(f"/org/roster?id={form['event_id']}")

    def _export(self, user) -> None:
        event_id = int(self._form()["id"])
        text = self.system.stats.export_csv(user, event_id, True)
        data = text.encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f"attachment; filename=event-{event_id}.csv")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _change_page(self, user, query) -> None:
        self._need(user, Role.ORGANIZER)
        event_id = int(_q(query, "id") or "0")
        event = self.system.events.detail(user, event_id)["event"]
        blocks = []
        for request in self.system.events.changes_of(user, event_id):
            lines = [f"<h3>申请 {request.id} · {esc(request.status.value)}</h3><p class=\"tiny\">{esc(request.note)}</p>"]
            for item in self.system.events.change_items(user, request.id):
                lines.append(
                    f'<div class="compare" style="margin-top:8px"><div class="old"><span class="tiny">原值</span><br><b>{esc(item.old_value)}</b></div>'
                    f'<div class="arrow">→</div><div class="new"><span class="tiny">{esc(item.field)}</span><br><b>{esc(item.new_value)}</b></div></div>'
                )
            blocks.append('<section class="card block" style="margin-top:12px">' + "".join(lines) + "</section>")
        body = f"""
{self._side(user, "变更申请", self._org_links(event_id))}
<main class="main">
  <div class="page-head"><div><h1>关键信息变更 · {esc(event.title)}</h1>
  <p class="sub">只能改场次时间、票种价格、场次容量。审核结束前，参与者看到的仍是原值。</p></div></div>
  {self._banner()}
  <div class="note">新容量不能小于已报名数。组织者不能审核自己的申请。</div>
  <form class="card block" style="margin-top:14px" method="post" action="/org/change-do">
    <input type="hidden" name="event_id" value="{event_id}">
    <div class="form-grid">
      <label class="field"><span>对象</span><select name="target_type"><option>场次</option><option>票种</option></select></label>
      <label class="field"><span>对象编号</span><input name="target_id"></label>
      <label class="field"><span>字段</span>
        <select name="field">{self._options(["开始时间", "结束时间", "报名截止时间", "容量", "价格"], "容量")}</select></label>
      <label class="field"><span>新值</span><input name="value"></label>
      <label class="field full"><span>申请说明</span><textarea name="note" rows="2"></textarea></label>
    </div>
    <button class="btn primary" style="margin-top:12px" type="submit">提交变更申请</button>
  </form>
  {''.join(blocks)}
</main></div>"""
        self._html("关键信息变更 · 活动汇", body, shell=True)

    def _change(self, user) -> None:
        form = self._form()
        spec = (form.get("target_type"), int(form.get("target_id") or "0"), form.get("field"), form.get("value"))
        self.system.events.request_change(user, int(form["event_id"]), [spec], form.get("note", ""))
        self._remember("变更已提交。审核通过前，对外仍是原值。")
        self._redirect(f"/org/change?id={form['event_id']}")

    def _admin_events(self, user) -> None:
        self._need(user, Role.ADMIN)
        cards = []
        for event in self.system.events.list_all(user):
            if event.status not in {EventStatus.PENDING, EventStatus.PUBLISHED, EventStatus.OFFLINE}:
                continue
            data = self.system.events.detail(user, event.id)
            bits = "；".join(
                f"{session.name} 容量 {session.capacity}" for session in data["sessions"]
            )
            buttons = ""
            if event.status == EventStatus.PENDING:
                buttons = (
                    f'<form method="post" action="/admin/approve"><input type="hidden" name="id" value="{event.id}">'
                    f'<button class="btn primary" type="submit">通过并发布</button></form>'
                    f'<form method="post" action="/admin/reject"><input type="hidden" name="id" value="{event.id}">'
                    f'<input name="reason" placeholder="驳回原因" style="height:36px"><button class="btn" type="submit">驳回</button></form>'
                )
            elif event.status == EventStatus.PUBLISHED:
                buttons = (
                    f'<form method="post" action="/admin/offline"><input type="hidden" name="id" value="{event.id}">'
                    f'<button class="btn" type="submit">下架</button></form>'
                    f'<form method="post" action="/org/cancel-do"><input type="hidden" name="id" value="{event.id}">'
                    f'<input type="hidden" name="reason" value="管理员强制取消">'
                    f'<button class="btn danger" type="submit">强制取消</button></form>'
                )
            cards.append(f"""
<article class="card block">
  {pill(event.status.value, status_kind(event.status.value))}
  <h2 style="margin-top:8px">{esc(event.title)}</h2>
  <div class="kvs"><i>城市 / 分类</i><span>{esc(event.city)} · {esc(event.category)}</span>
  <i>场次</i><span>{esc(bits or "无")}</span>
  <i>报名</i><span>{"需要组织者审核" if event.need_review else "报名即通过"}</span>
  <i>驳回原因</i><span>{esc(event.reject_reason or "无")}</span></div>
  <div class="row" style="margin-top:12px">{buttons}</div>
</article>""")
        body = f"""
{self._admin_side(user, "活动审核")}
<main class="main">
  <div class="page-head"><div><h1>活动审核</h1>
  <p class="sub">通过后自动发布。驳回必须写原因。不能在这里改组织者的票价和场次。</p></div></div>
  {self._banner()}
  <div class="split">{''.join(cards) or '<p class="tiny">没有待处理的活动。</p>'}</div>
</main></div>"""
        self._html("活动审核 · 活动汇", body, shell=True)

    def _admin_approve(self, user) -> None:
        self.system.events.approve(user, int(self._form()["id"]))
        self._redirect("/admin")

    def _admin_reject(self, user) -> None:
        form = self._form()
        self.system.events.reject(user, int(form["id"]), form.get("reason", ""))
        self._redirect("/admin")

    def _admin_offline(self, user) -> None:
        self.system.events.take_offline(user, int(self._form()["id"]), True)
        self._redirect("/admin")

    def _admin_changes(self, user) -> None:
        self._need(user, Role.ADMIN)
        cards = []
        for request in self.system.events.pending_changes(user):
            lines = []
            for item in self.system.events.change_items(user, request.id):
                lines.append(
                    f'<div class="compare"><div class="old"><span class="tiny">原值 · {esc(item.field)}</span><br><b>{esc(item.old_value)}</b></div>'
                    f'<div class="arrow">→</div><div class="new"><span class="tiny">新值</span><br><b>{esc(item.new_value)}</b></div></div>'
                )
            cards.append(f"""
<article class="card block">
  <h2>活动 {request.event_id} 的变更</h2>
  <p class="tiny">{esc(request.note)}</p>
  {''.join(lines)}
  <form method="post" action="/admin/change" style="margin-top:12px">
    <input type="hidden" name="id" value="{request.id}">
    <input name="comment" placeholder="审核意见" style="height:36px">
    <button class="btn primary" name="accept" value="1" type="submit">通过并生效</button>
    <button class="btn" name="accept" value="0" type="submit">驳回</button>
  </form>
</article>""")
        body = f"""
{self._admin_side(user, "变更审核")}
<main class="main">
  <div class="page-head"><div><h1>变更审核</h1>
  <p class="sub">通过前不影响正在生效的时间、价格和容量。不能审核自己组织的活动。</p></div></div>
  {self._banner()}
  {''.join(cards) or '<p class="tiny">没有待审核的变更。</p>'}
</main></div>"""
        self._html("变更审核 · 活动汇", body, shell=True)

    def _admin_change(self, user) -> None:
        form = self._form()
        self.system.events.review_change(
            user, int(form["id"]), form.get("accept") == "1", form.get("comment", ""), True
        )
        self._redirect("/admin/changes")

    def _admin_users(self, user) -> None:
        self._need(user, Role.ADMIN)
        rows = []
        for item in self.system.users.list_users(user):
            state = "启用" if item.enabled else "停用"
            rows.append(
                f"<tr><td>{esc(item.username)}</td><td class=\"num\">{esc(item.phone)}</td>"
                f"<td>{esc(item.role.value)}</td><td>{state}</td>"
                f"<td>{self._post_button('/admin/user', {'id': item.id, 'op': 'off' if item.enabled else 'on'}, '停用' if item.enabled else '启用')}</td></tr>"
            )
        body = f"""
{self._admin_side(user, "用户与权限")}
<main class="main">
  <div class="page-head"><div><h1>用户与权限</h1>
  <p class="sub">改角色和停用账号都要二次确认。不能停用自己，也不能改自己的角色。</p></div></div>
  {self._banner()}
  <form class="card block" method="post" action="/admin/user" style="margin-bottom:14px">
    <input type="hidden" name="op" value="create">
    <div class="form-grid">
      <label class="field"><span>用户名</span><input name="username"></label>
      <label class="field"><span>手机号</span><input name="phone"></label>
      <label class="field"><span>密码</span><input name="password" value="123456"></label>
      <label class="field"><span>角色</span><select name="role">{self._options([role.value for role in Role], "参与者")}</select></label>
    </div>
    <button class="btn primary" style="margin-top:12px" type="submit">创建账号</button>
  </form>
  <section class="card"><table>
    <thead><tr><th>用户名</th><th>手机号</th><th>角色</th><th>状态</th><th></th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></section>
</main></div>"""
        self._html("用户与权限 · 活动汇", body, shell=True)

    def _admin_user(self, user) -> None:
        form = self._form()
        op = form.get("op")
        if op == "create":
            role = next(item for item in Role if item.value == form.get("role"))
            self.system.users.create_user(
                user, form.get("username", ""), form.get("phone", ""), form.get("password", ""), role
            )
        elif op in {"on", "off"}:
            self.system.users.set_enabled(user, int(form["id"]), op == "on", True)
        self._redirect("/admin/users")

    def _logs(self, user, query) -> None:
        rows = self.system.audit.query(
            user,
            action=_q(query, "action") or None,
            event_id=int(_q(query, "event")) if _q(query, "event").isdigit() else None,
        )
        body_rows = []
        for row in rows[:80]:
            body_rows.append(
                "<tr>"
                f'<td class="num">{esc(row.created_at)}</td><td>{esc(row.action)}</td>'
                f"<td>{esc(row.result)}</td><td>{esc(row.detail)}</td>"
                f'<td class="num">{esc(row.event_id or "")}</td></tr>'
            )
        shell = user.role != Role.PARTICIPANT
        nav = ""
        if user.role == Role.ADMIN:
            nav = self._admin_side(user, "操作日志")
        elif user.role == Role.ORGANIZER:
            nav = self._side(user, "操作日志", [("我的活动", "/org"), ("操作日志", "/logs")])
        elif user.role == Role.CHECKER:
            nav = self._side(user, "操作日志", [("核销工作台", "/checkin"), ("操作日志", "/logs")], "检票工作台")
        inner = f"""
<main class="{'main' if shell else ''}">
  <div class="{'page' if not shell else ''}">
  <div class="page-head"><div><h1>操作日志</h1>
  <p class="sub">可以按操作类型和活动编号查询。日志只能追加，页面上不能改、不能删。</p></div></div>
  <form class="card filters" method="get" action="/logs">
    <label class="field"><span>操作类型</span><input name="action" value="{esc(_q(query,'action'))}" placeholder="报名"></label>
    <label class="field"><span>活动编号</span><input name="event" value="{esc(_q(query,'event'))}"></label>
    <button class="btn primary" type="submit">查询</button>
  </form>
  <section class="card"><table>
    <thead><tr><th>时间</th><th>操作</th><th>结果</th><th>详情</th><th>活动</th></tr></thead>
    <tbody>{''.join(body_rows) or '<tr><td colspan="5" class="tiny">没有记录。</td></tr>'}</tbody>
  </table></section>
  </div>
</main>"""
        if shell:
            self._html("操作日志 · 活动汇", nav + inner, shell=True)
        else:
            self._html("操作日志 · 活动汇", self._top(user, "通知") + inner)

    def _checkin_page(self, user, query) -> None:
        grants = self.system.checkin.granted_events(user)
        if not grants and user.role != Role.CHECKER:
            raise AppError("你还没有被授权核销任何活动")
        event_id = int(_q(query, "event") or "0")
        if not event_id and grants:
            event_id = grants[0].id
        options = "".join(
            f'<option value="{item.id}"{" selected" if item.id == event_id else ""}>{esc(item.title)}</option>'
            for item in grants
        )
        result = self._box().pop("checkin", None)
        if result and result.get("ok"):
            box = f'<div class="result-box note ok"><b>签到成功</b><p class="tiny" style="color:inherit">{esc(result["text"])}</p></div>'
        elif result:
            box = f'<div class="result-box note bad"><b>不能核销</b><p class="tiny" style="color:inherit">{esc(result["text"])}</p></div>'
        else:
            box = ""
        roster = ""
        if event_id:
            for row in self._roster_rows(user, event_id):
                roster += (
                    f'<tr><td class="num">{esc(row["code"])}</td><td>{esc(row["username"])}</td>'
                    f'<td>{esc(row["ticket"])}</td><td>{pill(row["signed"], "ok" if row["signed"] == "已签到" else "")}</td></tr>'
                )
        body = f"""
{self._side(user, "核销工作台", [("核销工作台", "/checkin"), ("操作日志", "/logs")], "检票工作台")}
<main class="main">
  <div class="page-head"><div><h1>核销</h1>
  <p class="sub">只能核销被授权的活动。扫码或输入报名号均可。本期不做实名校验。没有导出。</p></div>
  <form method="get" action="/checkin"><select name="event" onchange="this.form.submit()">{options}</select></form></div>
  <div class="checkin">
    <section class="card block">
      <h3>报名号</h3>
      <form method="post" action="/checkin">
        <input type="hidden" name="event" value="{event_id}">
        <input class="big-input" name="code" placeholder="BM00000001">
        <button class="btn primary" style="width:100%;height:42px;margin-top:12px" type="submit">确认核销</button>
      </form>
      {box}
    </section>
    <section class="card">
      <div class="block" style="padding-bottom:0"><h3>本活动名单</h3><p class="tiny">只能看这场的名单，没有导出。</p></div>
      <table><thead><tr><th>报名号</th><th>用户</th><th>票种</th><th>签到</th></tr></thead>
      <tbody>{roster}</tbody></table>
    </section>
  </div>
</main></div>"""
        self._html("核销 · 活动汇", body, shell=True)

    def _checkin(self, user) -> None:
        form = self._form()
        try:
            result = self.system.checkin.redeem(user, form.get("code", ""))
            text = f"{result['username']} · {result['ticket']} · {result['code']} · {result['checked_at']}"
            self._box()["checkin"] = {"ok": True, "text": text}
        except AppError as exc:
            self._box()["checkin"] = {"ok": False, "text": str(exc)}
        self._redirect(f"/checkin?event={form.get('event', '')}")

    def _roster_rows(self, user, event_id: int) -> list:
        try:
            return self.system.stats.roster(user, event_id)
        except AppError:
            return []

    def _ticket_view(self, user, session_id: int, ticket_id: int) -> dict:
        conn = self.system.database.connect()
        try:
            session = repo.get_session(conn, session_id)
            event = repo.get_event(conn, session.event_id)
            ticket = repo.get_ticket(conn, ticket_id)
        finally:
            conn.close()
        if ticket.session_id != session.id:
            raise AppError("票种不属于该场次")
        self.system.events.detail(user, event.id)
        return {"event": event, "session": session, "ticket": ticket}

    def _session_closed(self, session) -> bool:
        now = self.system.clock.now().strftime("%Y-%m-%d %H:%M:%S")
        return now > session.deadline

    def _top(self, user, active: str) -> str:
        unread = sum(1 for item in self.system.notify.list_mine(user) if not item.read_at)
        badge = f' <span class="badge">{unread}</span>' if unread else ""
        links = [
            ("发现活动", "/discover"),
            ("我的报名", "/mine"),
            ("通知", "/notices"),
        ]
        if user.role == Role.ORGANIZER:
            links.append(("组织者工作台", "/org"))
        if user.role == Role.ADMIN:
            links.append(("管理工作台", "/admin"))
        if self.system.users.my_grants(user) or user.role == Role.CHECKER:
            links.append(("核销", "/checkin"))
        nav = "".join(
            f'<a href="{href}"{_mark(name == active)}>{name}{badge if name == "通知" else ""}</a>'
            for name, href in links
        )
        return f"""
<header class="top">
  <div class="brand"><span class="mark">汇</span>活动汇</div>
  <nav>{nav}</nav>
  <div class="who">{esc(user.username)} <em>{esc(user.role.value)}</em> <a href="/logout">退出</a></div>
</header>"""

    def _side(self, user, active: str, links: list[tuple[str, str]], desk: str = "组织者工作台") -> str:
        nav = "".join(
            f'<a href="{href}"{_mark(name == active)}>{esc(name)}</a>'
            for name, href in links
        )
        return f"""
<div class="shell"><aside class="side">
  <div class="brand"><span class="mark">汇</span>活动汇</div>
  <div class="who-box">{esc(user.username)}<br>{esc(desk)}</div>
  {nav}
  <div class="gap"></div>
  <a href="/logout">退出登录</a>
</aside>"""

    def _admin_side(self, user, active: str) -> str:
        return self._side(
            user, active,
            [("活动审核", "/admin"), ("变更审核", "/admin/changes"),
             ("用户与权限", "/admin/users"), ("操作日志", "/logs")],
            "管理工作台",
        )

    def _org_links(self, event_id: int) -> list[tuple[str, str]]:
        return [
            ("我的活动", "/org"),
            ("新建活动", "/org/edit"),
            ("报名名单", f"/org/roster?id={event_id}"),
            ("变更申请", f"/org/change?id={event_id}"),
        ]

    def _steps(self, current: int) -> str:
        names = ["活动详情", "确认报名", "查看结果"]
        parts = []
        for index, name in enumerate(names, start=1):
            kind = "on" if index == current else "done" if index < current else ""
            parts.append(f'<div class="step {kind}"><i>{index}</i>{name}</div>')
        return f'<div class="steps">{"".join(parts)}</div>'

    def _banner(self) -> str:
        text = self._box().pop("message", "")
        if not text:
            return ""
        return f'<div class="note ok" style="margin-bottom:12px">{esc(text)}</div>'

    def _options(self, values: list[str], current: str) -> str:
        return "".join(
            f'<option{" selected" if item == current else ""}>{esc(item)}</option>' for item in values
        )

    def _options_pairs(self, pairs: list[tuple[str, str]], current: str) -> str:
        return "".join(
            f'<option value="{esc(value)}"{" selected" if value == current else ""}>{esc(label)}</option>'
            for value, label in pairs
        )

    def _post_button(self, action: str, fields: dict, label: str) -> str:
        hidden = "".join(
            f'<input type="hidden" name="{esc(key)}" value="{esc(value)}">' for key, value in fields.items()
        )
        return f'<form method="post" action="{action}" style="display:inline">{hidden}<button class="btn tiny" type="submit">{esc(label)}</button></form>'

    def _need(self, user, role: Role) -> None:
        if user.role != role:
            raise AppError("无权限")

    def _home(self, user) -> str:
        if user.role == Role.ORGANIZER:
            return "/org"
        if user.role == Role.ADMIN:
            return "/admin"
        if user.role == Role.CHECKER:
            return "/checkin"
        return "/discover"

    def _user(self):
        sid = self._sid()
        with _LOCK:
            box = _SESSIONS.get(sid)
        if not box:
            return None
        conn = self.system.database.connect()
        try:
            return repo.get_user(conn, box["user_id"])
        finally:
            conn.close()

    def _sid(self) -> str:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "sid":
                return value
        return ""

    def _box(self) -> dict:
        sid = self._sid()
        with _LOCK:
            return _SESSIONS.setdefault(sid, {})

    def _remember(self, message: str) -> None:
        self._box()["message"] = message

    def _form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[-1] for key, values in parsed.items()}

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _flash_back(self, message: str) -> None:
        referer = self.headers.get("Referer", "/")
        join = "&" if "?" in referer else "?"
        self._redirect(referer + join + "err=" + quote(message))

    def _css(self) -> None:
        data = STATIC.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, title: str, body: str, bare: bool = False, shell: bool = False) -> None:
        err = parse_qs(urlparse(self.path).query).get("err", [""])[0]
        if err and not bare:
            note = f'<div class="note bad" style="margin:0 0 12px">{esc(err)}</div>'
            marker = '<main class="main">'
            if shell and marker in body:
                body = body.replace(marker, marker + note, 1)
            else:
                body = note + body
        if shell:
            body += "</div>"
        page = (
            "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            f"<title>{esc(title)}</title><link rel=\"stylesheet\" href=\"/site.css\"></head><body>"
            f"{body}</body></html>"
        )
        data = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _mark(active: bool) -> str:
    return ' class="on"' if active else ""


def _q(query: dict, key: str) -> str:
    return (query.get(key) or [""])[0].strip()


def _port_in_use(port: int) -> bool:
    """8765 上如果已经是活动汇，再启动一次就不要抢端口。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def start_server(db_path=None, port: int = 8765):
    """在后台监听。返回服务、端口，以及这次是不是新启动的。"""
    if _port_in_use(port):
        return None, port, False
    HubHandler.system = System(db_path)
    server = None
    chosen = port
    last_error = None
    for chosen in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", chosen), HubHandler)
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise OSError(f"从 {port} 起的端口都无法监听") from last_error
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for _ in range(50):
        if _port_in_use(chosen):
            return server, chosen, True
        threading.Event().wait(0.1)
    return server, chosen, True


def run(db_path=None, port: int = 8765, open_browser: bool = True) -> None:
    """只在浏览器里打开。桌面图标走 desktop.run。"""
    _server, chosen, _owned = start_server(db_path, port)
    url = f"http://127.0.0.1:{chosen}/login"
    print(f"活动汇已启动：{url}")
    if open_browser:
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        if _server is not None:
            _server.shutdown()
