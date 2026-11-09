# -*- coding: utf-8 -*-
"""桌面界面。只调用业务包，不直接修改已报名数或候补数。"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ticketapp.errors import AppError
from ticketapp.models import Role
from ticketapp.system import System

FONT = ("Microsoft YaHei UI", 10)
TITLE_FONT = ("Microsoft YaHei UI", 16)


def run(db_path=None) -> None:
    """启动图形界面。"""
    root = tk.Tk()
    TicketApp(root, db_path)
    root.mainloop()


class TicketApp:
    """登录后按角色显示功能。"""

    def __init__(self, root: tk.Tk, db_path=None) -> None:
        self.root = root
        self.system = System(db_path)
        self.actor = None
        self.root.title("活动票务与报名系统")
        self.root.geometry("1120x740")
        self.root.minsize(980, 640)
        self._style()
        self.shell = ttk.Frame(root, padding=12)
        self.shell.pack(fill="both", expand=True)
        self._show_login()

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=FONT)
        style.configure("Treeview", rowheight=26, font=FONT)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", padding=(8, 4))
        self.root.configure(bg="#F4F1EA")

    def _clear(self) -> None:
        for child in self.shell.winfo_children():
            child.destroy()

    def _show_login(self) -> None:
        self._clear()
        box = ttk.Frame(self.shell, padding=24)
        box.place(relx=0.5, rely=0.46, anchor="center")
        ttk.Label(box, text="活动票务与报名系统", font=TITLE_FONT).grid(
            row=0, column=0, columnspan=2, pady=(0, 16)
        )
        ttk.Label(box, text="用户名").grid(row=1, column=0, sticky="e", pady=4)
        ttk.Label(box, text="密码").grid(row=2, column=0, sticky="e", pady=4)
        self.name_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        name = ttk.Entry(box, textvariable=self.name_var, width=28)
        password = ttk.Entry(box, textvariable=self.pass_var, width=28, show="*")
        name.grid(row=1, column=1, pady=4)
        password.grid(row=2, column=1, pady=4)
        ttk.Button(box, text="登录", command=self._login).grid(
            row=3, column=0, columnspan=2, pady=12
        )
        hint = (
            "演示账号的密码都是 123456\n"
            "管理员 admin    组织者 organizer\n"
            "参与者 linxiao / zhou / chen\n"
            "检票人员 checker"
        )
        ttk.Label(box, text=hint, justify="left").grid(row=4, column=0, columnspan=2)
        password.bind("<Return>", lambda _event: self._login())
        name.focus_set()

    def _login(self) -> None:
        self.sign_in(self.name_var.get(), self.pass_var.get())

    def sign_in(self, username: str, password: str) -> None:
        """登录并进入主界面。密码错误时只提示，不抛到界面外。"""
        try:
            self.actor = self.system.users.login(username, password)
        except AppError as exc:
            messagebox.showwarning("无法登录", str(exc))
            return
        self._show_main()

    def show_page(self, name: str) -> None:
        """切换到指定功能页。"""
        self._open_page(name)

    def _show_main(self) -> None:
        self._clear()
        top = ttk.Frame(self.shell)
        top.pack(fill="x")
        ttk.Label(
            top,
            text=f"{self.actor.username}　{self.actor.role.value}",
            font=("Microsoft YaHei UI", 12),
        ).pack(side="left")
        ttk.Button(top, text="退出", command=self._show_login).pack(side="right")
        body = ttk.Frame(self.shell)
        body.pack(fill="both", expand=True, pady=(12, 0))
        self.nav = tk.Listbox(body, width=16, font=FONT, activestyle="none", exportselection=False)
        self.nav.pack(side="left", fill="y")
        self.content = ttk.Frame(body, padding=(12, 0, 0, 0))
        self.content.pack(side="left", fill="both", expand=True)
        for name in self._pages():
            self.nav.insert("end", name)
        self.nav.bind("<<ListboxSelect>>", self._on_nav)
        self.nav.selection_set(0)
        self._open_page(self._pages()[0])

    def _pages(self) -> list[str]:
        pages = ["浏览活动", "我的报名", "我的通知", "操作日志"]
        if self.actor.role == Role.ORGANIZER:
            pages.append("活动管理")
        if self.actor.role == Role.ADMIN:
            pages.append("平台管理")
        grants = self.system.users.my_grants(self.actor)
        if self.actor.role == Role.CHECKER or grants:
            pages.append("签到核销")
        return pages

    def _on_nav(self, _event) -> None:
        selected = self.nav.curselection()
        if selected:
            self._open_page(self.nav.get(selected[0]))

    def _open_page(self, name: str) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        pages = {
            "浏览活动": self._page_browse,
            "我的报名": self._page_regs,
            "我的通知": self._page_notices,
            "操作日志": self._page_logs,
            "活动管理": self._page_events,
            "平台管理": self._page_admin,
            "签到核销": self._page_checkin,
        }
        pages[name]()

    def _page_browse(self) -> None:
        filters = ttk.Frame(self.content)
        filters.pack(fill="x")
        fields = [
            ("关键词", "keyword"), ("分类", "category"), ("城市", "city"),
            ("开始日期", "date_from"), ("结束日期", "date_to"),
            ("最低价", "price_min"), ("最高价", "price_max"), ("状态", "status"),
        ]
        self.browse_vars = {}
        for index, (label, key) in enumerate(fields):
            ttk.Label(filters, text=label).grid(row=index // 4, column=(index % 4) * 2, sticky="e")
            var = tk.StringVar()
            ttk.Entry(filters, textvariable=var, width=14).grid(
                row=index // 4, column=(index % 4) * 2 + 1, padx=(4, 10), pady=3
            )
            self.browse_vars[key] = var
        ttk.Label(
            self.content, text="状态可填：报名中、已满、已结束。日期格式 YYYY-MM-DD。"
        ).pack(anchor="w", pady=4)
        buttons = ttk.Frame(self.content)
        buttons.pack(fill="x", pady=4)
        ttk.Button(buttons, text="查询", command=self._search).pack(side="left")
        ttk.Button(
            buttons, text="查看并报名", command=self._open_selected_event
        ).pack(side="left", padx=8)
        self.browse_tip = ttk.Label(self.content, text="")
        self.browse_tip.pack(anchor="w")
        self.browse_tree = self._make_tree(
            self.content,
            ("title", "city", "category", "status", "price", "start"),
            (("title", "活动", 220), ("city", "城市", 80), ("category", "分类", 80),
             ("status", "状态", 80), ("price", "价格", 120), ("start", "首场开始", 160)),
        )
        self.browse_tree.bind("<Double-1>", lambda _event: self._open_selected_event())
        self._search()

    def _search(self) -> None:
        values = {key: var.get().strip() for key, var in self.browse_vars.items()}
        try:
            rows = self.system.events.search(self.actor, **values)
        except AppError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        self._fill(self.browse_tree, rows, lambda row: (
            str(row["id"]),
            (row["title"], row["city"], row["category"], row["browse_status"],
             row["price_text"], row["start_text"]),
        ))
        self.browse_tip.configure(
            text="没有符合条件的活动" if not rows else f"共 {len(rows)} 个活动"
        )

    def _open_selected_event(self) -> None:
        event_id = self._selected_id(self.browse_tree)
        if event_id is None:
            messagebox.showinfo("提示", "请先选择一个活动")
            return
        self._event_dialog(event_id)

    def _event_dialog(self, event_id: int) -> None:
        try:
            data = self.system.events.detail(self.actor, event_id)
        except AppError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        event = data["event"]
        win = tk.Toplevel(self.root)
        win.title(event.title)
        win.geometry("760x520")
        win.transient(self.root)
        text = (
            f"{event.title}　{event.city}　{event.category}\n"
            f"状态：{data['browse_status']}　"
            f"{'报名需要审核' if event.need_review else '报名即通过'}\n\n"
            f"{event.intro}\n\n"
            "余量只供参考。提交时会重新核对场次状态、截止时间和是否重复报名。"
        )
        ttk.Label(win, text=text, wraplength=720, justify="left").pack(anchor="w", padx=12, pady=8)
        tree = self._make_tree(
            win,
            ("session", "ticket", "price", "remain"),
            (("session", "场次", 180), ("ticket", "票种", 140),
             ("price", "价格", 100), ("remain", "剩余/容量", 120)),
        )
        for session in data["sessions"]:
            for ticket in data["tickets"].get(session.id, []):
                tree.insert("", "end", iid=f"{session.id}-{ticket.id}", values=(
                    session.name, ticket.name, ticket.charge_label(),
                    f"{session.remaining()}/{session.capacity}",
                ))
        if self.actor.role == Role.PARTICIPANT:
            ttk.Button(
                win, text="报名所选票种",
                command=lambda: self._register(tree, win),
            ).pack(anchor="w", padx=12, pady=8)

    def _register(self, tree: ttk.Treeview, win: tk.Toplevel) -> None:
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请选择场次和票种", parent=win)
            return
        session_id, ticket_id = (int(part) for part in selected[0].split("-"))
        values = tree.item(selected[0], "values")
        if not messagebox.askyesno(
            "确认报名",
            f"确认报名「{values[0]} / {values[1]}」？\n这一步会按当前场次重新校验。",
            parent=win,
        ):
            return
        try:
            record = self.system.regs.register(self.actor, session_id, ticket_id)
        except AppError as exc:
            messagebox.showwarning("报名未成功", str(exc), parent=win)
            return
        messagebox.showinfo(
            "报名结果",
            f"报名号 {record.code}\n当前状态：{record.status.value}",
            parent=win,
        )
        win.destroy()

    def _page_regs(self) -> None:
        ttk.Button(self.content, text="刷新", command=self._load_regs).pack(anchor="w")
        ttk.Button(self.content, text="取消所选报名", command=self._cancel_reg).pack(anchor="w", pady=4)
        self.reg_tree = self._make_tree(
            self.content,
            ("code", "event", "session", "ticket", "status", "pay", "time"),
            (("code", "报名号", 110), ("event", "活动", 160), ("session", "场次", 100),
             ("ticket", "票种", 80), ("status", "状态", 80), ("pay", "支付", 80),
             ("time", "报名时间", 150)),
        )
        self._load_regs()

    def _load_regs(self) -> None:
        rows = self.system.regs.list_mine(self.actor)
        self._fill(self.reg_tree, rows, lambda row: (
            str(row["id"]),
            (row["code"], row["event_title"], row["session_name"], row["ticket_name"],
             row["status"], row["payment_status"] or "—", row["created_at"]),
        ))

    def _cancel_reg(self) -> None:
        reg_id = self._selected_id(self.reg_tree)
        if reg_id is None:
            messagebox.showinfo("提示", "请选择一条报名")
            return
        if not messagebox.askyesno("取消报名", "确认取消这条报名？"):
            return
        try:
            record = self.system.regs.cancel(self.actor, reg_id)
        except AppError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        messagebox.showinfo("已取消", f"当前状态：{record.status.value}")
        self._load_regs()

    def _page_notices(self) -> None:
        ttk.Button(self.content, text="标记已读", command=self._read_notice).pack(anchor="w")
        self.notice_tree = self._make_tree(
            self.content,
            ("type", "content", "time", "read"),
            (("type", "类型", 100), ("content", "内容", 460),
             ("time", "时间", 150), ("read", "已读", 140)),
        )
        self._load_notices()

    def _load_notices(self) -> None:
        rows = self.system.notify.list_mine(self.actor)
        self._fill(self.notice_tree, rows, lambda row: (
            str(row.id),
            (row.ntype.value, row.content, row.created_at, row.read_at or "未读"),
        ))

    def _read_notice(self) -> None:
        notice_id = self._selected_id(self.notice_tree)
        if notice_id is None:
            return
        try:
            self.system.notify.mark_read(self.actor, notice_id)
        except AppError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        self._load_notices()

    def _page_logs(self) -> None:
        toolbar = ttk.Frame(self.content)
        toolbar.pack(fill="x")
        self.log_action = tk.StringVar()
        self.log_event = tk.StringVar()
        ttk.Label(toolbar, text="操作类型").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.log_action, width=12).pack(side="left", padx=4)
        ttk.Label(toolbar, text="活动编号").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.log_event, width=8).pack(side="left", padx=4)
        ttk.Button(toolbar, text="查询", command=self._load_logs).pack(side="left", padx=6)
        self.log_tree = self._make_tree(
            self.content,
            ("time", "action", "result", "detail", "event"),
            (("time", "时间", 150), ("action", "操作", 100), ("result", "结果", 70),
             ("detail", "详情", 320), ("event", "活动", 70)),
        )
        self._load_logs()

    def _load_logs(self) -> None:
        event_text = self.log_event.get().strip()
        event_id = int(event_text) if event_text.isdigit() else None
        try:
            rows = self.system.audit.query(
                self.actor, action=self.log_action.get().strip() or None, event_id=event_id
            )
        except AppError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        self._fill(self.log_tree, rows, lambda row: (
            str(row.id),
            (row.created_at, row.action, row.result, row.detail, row.event_id or ""),
        ))

    def _page_events(self) -> None:
        form = ttk.LabelFrame(self.content, text="新建活动", padding=8)
        form.pack(fill="x")
        self.new_title = tk.StringVar()
        self.new_category = tk.StringVar(value="文艺")
        self.new_city = tk.StringVar(value="南京")
        self.new_intro = tk.StringVar()
        self.new_review = tk.BooleanVar(value=False)
        self._labeled_entry(form, "标题", self.new_title, 0)
        self._labeled_entry(form, "分类", self.new_category, 1)
        self._labeled_entry(form, "城市", self.new_city, 2)
        self._labeled_entry(form, "介绍", self.new_intro, 3)
        ttk.Checkbutton(form, text="报名需要审核", variable=self.new_review).grid(
            row=0, column=4, padx=8
        )
        ttk.Button(form, text="创建草稿", command=self._create_event).grid(row=1, column=4, padx=8)
        ttk.Button(self.content, text="打开活动工作台", command=self._open_desk).pack(anchor="w", pady=6)
        self.own_tree = self._make_tree(
            self.content,
            ("title", "city", "status", "review"),
            (("title", "活动", 240), ("city", "城市", 80),
             ("status", "状态", 90), ("review", "报名审核", 100)),
            height=14,
        )
        self._load_owned()

    def _create_event(self) -> None:
        try:
            event = self.system.events.create_event(
                self.actor, self.new_title.get(), self.new_category.get(),
                self.new_city.get(), self.new_intro.get(), "", self.new_review.get(),
            )
        except AppError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        messagebox.showinfo("已创建", f"草稿已保存，活动编号 {event.id}")
        self._load_owned()

    def _load_owned(self) -> None:
        rows = self.system.events.list_owned(self.actor)
        self._fill(self.own_tree, rows, lambda row: (
            str(row.id),
            (row.title, row.city, row.status.value, "需要" if row.need_review else "不需要"),
        ))

    def _open_desk(self) -> None:
        event_id = self._selected_id(self.own_tree)
        if event_id is None:
            messagebox.showinfo("提示", "请选择一个活动")
            return
        EventDesk(self.root, self.system, self.actor, event_id, self._load_owned)

    def _page_admin(self) -> None:
        book = ttk.Notebook(self.content)
        book.pack(fill="both", expand=True)
        review = ttk.Frame(book, padding=8)
        changes = ttk.Frame(book, padding=8)
        users = ttk.Frame(book, padding=8)
        book.add(review, text="活动审核")
        book.add(changes, text="变更审核")
        book.add(users, text="用户")
        self.admin_tree = self._make_tree(
            review,
            ("title", "org", "status", "reason"),
            (("title", "活动", 220), ("org", "组织者", 80),
             ("status", "状态", 80), ("reason", "驳回原因", 220)),
            height=12,
        )
        toolbar = ttk.Frame(review)
        toolbar.pack(fill="x", pady=4)
        ttk.Button(toolbar, text="通过", command=self._approve_event).pack(side="left")
        ttk.Button(toolbar, text="驳回", command=self._reject_event).pack(side="left", padx=6)
        ttk.Button(toolbar, text="下架", command=self._offline_event).pack(side="left", padx=6)
        ttk.Button(toolbar, text="强制取消", command=self._force_cancel).pack(side="left", padx=6)
        ttk.Button(toolbar, text="刷新", command=self._load_admin_events).pack(side="left", padx=6)
        self.change_tree = self._make_tree(
            changes,
            ("event", "note", "status"),
            (("event", "活动编号", 100), ("note", "说明", 280), ("status", "状态", 80)),
            height=8,
        )
        change_bar = ttk.Frame(changes)
        change_bar.pack(fill="x", pady=4)
        ttk.Button(
            change_bar, text="通过变更", command=lambda: self._review_change(True)
        ).pack(side="left")
        ttk.Button(
            change_bar, text="驳回变更", command=lambda: self._review_change(False)
        ).pack(side="left", padx=6)
        ttk.Button(change_bar, text="查看变更项", command=self._show_change_items).pack(side="left")
        self._user_admin(users)
        self._load_admin_events()
        self._load_changes()

    def _load_admin_events(self) -> None:
        rows = self.system.events.list_all(self.actor)
        users = {user.id: user.username for user in self.system.users.list_users(self.actor)}
        self._fill(self.admin_tree, rows, lambda row: (
            str(row.id),
            (row.title, users.get(row.organizer_id, row.organizer_id),
             row.status.value, row.reject_reason),
        ))

    def _approve_event(self) -> None:
        self._admin_event_action(
            "通过该活动？",
            lambda event_id: self.system.events.approve(self.actor, event_id),
        )

    def _reject_event(self) -> None:
        event_id = self._selected_id(self.admin_tree)
        if event_id is None:
            return
        reason = simpledialog.askstring("驳回", "请填写驳回原因", parent=self.root)
        if not reason:
            return
        self._run(
            lambda: self.system.events.reject(self.actor, event_id, reason),
            self._load_admin_events,
        )

    def _offline_event(self) -> None:
        self._admin_event_action(
            "确认下架？已有报名会保留。",
            lambda event_id: self.system.events.take_offline(self.actor, event_id, True),
        )

    def _force_cancel(self) -> None:
        self._admin_event_action(
            "确认强制取消？有效报名会失效，收费票标记待退款。",
            lambda event_id: self.system.events.cancel_event(self.actor, event_id, True),
        )

    def _admin_event_action(self, question: str, action) -> None:
        event_id = self._selected_id(self.admin_tree)
        if event_id is None:
            messagebox.showinfo("提示", "请选择活动")
            return
        if not messagebox.askyesno("确认", question):
            return
        self._run(lambda: action(event_id), self._load_admin_events)

    def _load_changes(self) -> None:
        rows = self.system.events.pending_changes(self.actor)
        self._fill(self.change_tree, rows, lambda row: (
            str(row.id), (row.event_id, row.note, row.status.value),
        ))

    def _review_change(self, accept: bool) -> None:
        request_id = self._selected_id(self.change_tree)
        if request_id is None:
            return
        comment = simpledialog.askstring("审核意见", "请填写审核意见", parent=self.root) or ""
        if not messagebox.askyesno("确认", "确认提交这次变更审核？"):
            return
        self._run(
            lambda: self.system.events.review_change(
                self.actor, request_id, accept, comment, True
            ),
            self._load_changes,
        )

    def _show_change_items(self) -> None:
        request_id = self._selected_id(self.change_tree)
        if request_id is None:
            return
        try:
            items = self.system.events.change_items(self.actor, request_id)
        except AppError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        text = "\n".join(
            f"{item.target_type} {item.target_id} 的{item.field}：{item.old_value} → {item.new_value}"
            for item in items
        )
        messagebox.showinfo("变更项", text or "没有变更项")

    def _user_admin(self, parent) -> None:
        form = ttk.Frame(parent)
        form.pack(fill="x")
        self.u_name = tk.StringVar()
        self.u_phone = tk.StringVar()
        self.u_pass = tk.StringVar(value="123456")
        self.u_role = tk.StringVar(value=Role.PARTICIPANT.value)
        self._labeled_entry(form, "用户名", self.u_name, 0)
        self._labeled_entry(form, "手机", self.u_phone, 1)
        self._labeled_entry(form, "密码", self.u_pass, 2)
        ttk.Combobox(
            form, textvariable=self.u_role, width=12, state="readonly",
            values=[role.value for role in Role],
        ).grid(row=0, column=7, padx=4)
        ttk.Button(form, text="创建", command=self._create_user).grid(row=0, column=8, padx=4)
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", pady=4)
        ttk.Button(
            toolbar, text="停用", command=lambda: self._set_enabled(False)
        ).pack(side="left")
        ttk.Button(
            toolbar, text="启用", command=lambda: self._set_enabled(True)
        ).pack(side="left", padx=6)
        ttk.Button(toolbar, text="设为所选角色", command=self._set_role).pack(side="left")
        self.user_tree = self._make_tree(
            parent,
            ("name", "phone", "role", "enabled"),
            (("name", "用户名", 140), ("phone", "手机号", 120),
             ("role", "角色", 100), ("enabled", "状态", 70)),
            height=12,
        )
        self._load_users()

    def _load_users(self) -> None:
        rows = self.system.users.list_users(self.actor)
        self._fill(self.user_tree, rows, lambda row: (
            str(row.id),
            (row.username, row.phone, row.role.value, "启用" if row.enabled else "停用"),
        ))

    def _create_user(self) -> None:
        role = next(item for item in Role if item.value == self.u_role.get())
        self._run(
            lambda: self.system.users.create_user(
                self.actor, self.u_name.get(), self.u_phone.get(), self.u_pass.get(), role
            ),
            self._load_users,
        )

    def _set_enabled(self, enabled: bool) -> None:
        user_id = self._selected_id(self.user_tree)
        if user_id is None:
            return
        word = "启用" if enabled else "停用"
        if not messagebox.askyesno("确认", f"确认{word}该账号？"):
            return
        self._run(
            lambda: self.system.users.set_enabled(self.actor, user_id, enabled, True),
            self._load_users,
        )

    def _set_role(self) -> None:
        user_id = self._selected_id(self.user_tree)
        if user_id is None:
            return
        role = next(item for item in Role if item.value == self.u_role.get())
        if not messagebox.askyesno("确认", f"确认把角色改为{role.value}？"):
            return
        self._run(
            lambda: self.system.users.set_role(self.actor, user_id, role, True),
            self._load_users,
        )

    def _page_checkin(self) -> None:
        toolbar = ttk.Frame(self.content)
        toolbar.pack(fill="x")
        self.code_var = tk.StringVar()
        ttk.Label(toolbar, text="报名号").pack(side="left")
        entry = ttk.Entry(toolbar, textvariable=self.code_var, width=24)
        entry.pack(side="left", padx=6)
        ttk.Button(toolbar, text="核销", command=self._redeem).pack(side="left")
        entry.bind("<Return>", lambda _event: self._redeem())
        self.check_result = ttk.Label(self.content, text="等待核销", wraplength=700)
        self.check_result.pack(anchor="w", pady=8)
        self.check_event = tk.StringVar()
        events = self.system.checkin.granted_events(self.actor)
        names = [f"{event.id}:{event.title}" for event in events]
        if names:
            self.check_event.set(names[0])
            ttk.Combobox(
                self.content, textvariable=self.check_event, values=names, width=40
            ).pack(anchor="w")
            ttk.Button(self.content, text="查看本活动签到名单", command=self._load_check_roster).pack(
                anchor="w", pady=4
            )
        self.check_tree = self._make_tree(
            self.content,
            ("user", "code", "ticket", "status", "signed"),
            (("user", "用户", 100), ("code", "报名号", 120), ("ticket", "票种", 100),
             ("status", "报名状态", 90), ("signed", "签到", 80)),
        )
        if names:
            self._load_check_roster()

    def _redeem(self) -> None:
        try:
            result = self.system.checkin.redeem(self.actor, self.code_var.get())
        except AppError as exc:
            self.check_result.configure(text=str(exc))
            messagebox.showwarning("不能核销", str(exc))
            return
        self.check_result.configure(
            text=f"签到成功：{result['username']}　{result['event']}　{result['ticket']}　{result['code']}"
        )
        if self.check_event.get():
            self._load_check_roster()

    def _load_check_roster(self) -> None:
        raw = self.check_event.get().split(":", 1)[0]
        if not raw.isdigit():
            return
        try:
            rows = self.system.stats.roster(self.actor, int(raw))
        except AppError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        self._fill(self.check_tree, rows, lambda row: (
            str(row["id"]),
            (row["username"], row["code"], row["ticket"], row["status"], row["signed"]),
        ))

    def _make_tree(self, parent, columns, headings, height=10) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=4)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
        for key, text, width in headings:
            tree.heading(key, text=text)
            tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    @staticmethod
    def _fill(tree, rows, mapper) -> None:
        tree.delete(*tree.get_children())
        for row in rows:
            iid, values = mapper(row)
            tree.insert("", "end", iid=iid, values=values)

    @staticmethod
    def _selected_id(tree) -> int | None:
        selected = tree.selection()
        if not selected:
            return None
        return int(selected[0])

    @staticmethod
    def _labeled_entry(parent, label, variable, column) -> None:
        ttk.Label(parent, text=label).grid(row=0, column=column * 2, sticky="e")
        ttk.Entry(parent, textvariable=variable, width=14).grid(
            row=0, column=column * 2 + 1, padx=(4, 8), pady=3
        )

    @staticmethod
    def _run(action, refresh) -> None:
        try:
            action()
        except AppError as exc:
            messagebox.showwarning("提示", str(exc))
            return
        refresh()


class EventDesk:
    """组织者处理单个活动，仍然只调用业务服务。"""

    def __init__(self, root, system, actor, event_id: int, on_close) -> None:
        self.system = system
        self.actor = actor
        self.event_id = event_id
        self.on_close = on_close
        self.win = tk.Toplevel(root)
        self.win.title(f"活动工作台 #{event_id}")
        self.win.geometry("920x640")
        self.win.transient(root)
        book = ttk.Notebook(self.win, padding=8)
        book.pack(fill="both", expand=True)
        self.info = ttk.Frame(book, padding=8)
        self.plan = ttk.Frame(book, padding=8)
        self.people = ttk.Frame(book, padding=8)
        self.change = ttk.Frame(book, padding=8)
        self.report = ttk.Frame(book, padding=8)
        book.add(self.info, text="资料")
        book.add(self.plan, text="场次与票种")
        book.add(self.people, text="报名")
        book.add(self.change, text="变更")
        book.add(self.report, text="统计与导出")
        self._build_info()
        self._build_plan()
        self._build_people()
        self._build_change()
        self._build_report()
        self.reload()

    def reload(self) -> None:
        """重新读取活动并刷新工作台。"""
        data = self.system.events.detail(self.actor, self.event_id)
        event = data["event"]
        self.title_var.set(event.title)
        self.category_var.set(event.category)
        self.city_var.set(event.city)
        self.intro_var.set(event.intro)
        self.review_var.set(event.need_review)
        self.status_label.configure(
            text=f"状态：{event.status.value}　驳回原因：{event.reject_reason or '无'}"
        )
        self._fill_sessions(data)
        self._fill_people()
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", self.system.stats.summary_text(self.actor, self.event_id))
        self.report_text.configure(state="disabled")
        self.on_close()

    def _build_info(self) -> None:
        self.title_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.city_var = tk.StringVar()
        self.intro_var = tk.StringVar()
        self.review_var = tk.BooleanVar()
        form = self.info
        for row, (label, var) in enumerate((
            ("标题", self.title_var), ("分类", self.category_var),
            ("城市", self.city_var), ("介绍", self.intro_var),
        )):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="e", pady=3)
            ttk.Entry(form, textvariable=var, width=48).grid(row=row, column=1, sticky="w")
        ttk.Checkbutton(form, text="报名需要审核", variable=self.review_var).grid(
            row=4, column=1, sticky="w", pady=4
        )
        self.status_label = ttk.Label(form, text="")
        self.status_label.grid(row=5, column=1, sticky="w")
        toolbar = ttk.Frame(form)
        toolbar.grid(row=6, column=1, sticky="w", pady=8)
        ttk.Button(toolbar, text="保存资料", command=self._save_profile).pack(side="left")
        ttk.Button(toolbar, text="提交审核", command=self._submit).pack(side="left", padx=6)
        ttk.Button(toolbar, text="取消活动", command=self._cancel_event).pack(side="left")
        ttk.Button(toolbar, text="到期结算", command=self._settle).pack(side="left", padx=6)

    def _save_profile(self) -> None:
        self._run(lambda: self.system.events.update_profile(
            self.actor, self.event_id, self.title_var.get(), self.category_var.get(),
            self.city_var.get(), self.intro_var.get(), "", self.review_var.get(),
        ))

    def _submit(self) -> None:
        self._run(lambda: self.system.events.submit(self.actor, self.event_id))

    def _cancel_event(self) -> None:
        if not messagebox.askyesno("取消活动", "确认取消？有效报名会失效。", parent=self.win):
            return
        self._run(lambda: self.system.events.cancel_event(self.actor, self.event_id, True))

    def _settle(self) -> None:
        self._run(lambda: self.system.regs.settle_due(self.actor, self.event_id))

    def _build_plan(self) -> None:
        self.session_cache = {}
        self.session_name = tk.StringVar(value="第一场")
        self.session_place = tk.StringVar()
        self.session_start = tk.StringVar()
        self.session_end = tk.StringVar()
        self.session_deadline = tk.StringVar()
        self.session_capacity = tk.StringVar(value="30")
        self.ticket_name = tk.StringVar(value="免费票")
        self.ticket_price = tk.StringVar(value="0")
        form = ttk.Frame(self.plan)
        form.pack(fill="x")
        labels = (
            ("场次名", self.session_name), ("地点", self.session_place),
            ("开始", self.session_start), ("结束", self.session_end),
            ("截止", self.session_deadline), ("容量", self.session_capacity),
        )
        for index, (label, var) in enumerate(labels):
            ttk.Label(form, text=label).grid(row=index // 3, column=(index % 3) * 2, sticky="e")
            ttk.Entry(form, textvariable=var, width=18).grid(
                row=index // 3, column=(index % 3) * 2 + 1, padx=4, pady=2
            )
        ttk.Label(self.plan, text="时间格式 YYYY-MM-DD HH:MM。已发布后，时间和容量要走变更申请。").pack(
            anchor="w", pady=4
        )
        toolbar = ttk.Frame(self.plan)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="添加场次", command=self._add_session).pack(side="left")
        ttk.Button(toolbar, text="保存所选场次", command=self._save_session).pack(side="left", padx=6)
        ttk.Button(toolbar, text="删除所选场次", command=self._delete_session).pack(side="left")
        self.session_tree = self._tree(
            self.plan,
            ("name", "place", "start", "capacity", "enrolled"),
            (("name", "场次", 140), ("place", "地点", 140), ("start", "开始", 160),
             ("capacity", "容量", 70), ("enrolled", "已报名", 70)),
        )
        self.session_tree.bind("<<TreeviewSelect>>", self._pick_session)
        ticket_bar = ttk.Frame(self.plan)
        ticket_bar.pack(fill="x", pady=4)
        ttk.Entry(ticket_bar, textvariable=self.ticket_name, width=16).pack(side="left")
        ttk.Entry(ticket_bar, textvariable=self.ticket_price, width=8).pack(side="left", padx=4)
        ttk.Button(ticket_bar, text="给所选场次加票", command=self._add_ticket).pack(side="left")
        self.ticket_tree = self._tree(
            self.plan, ("name", "price"), (("name", "票种", 180), ("price", "价格", 120)),
        )

    def _fill_sessions(self, data) -> None:
        self.session_tree.delete(*self.session_tree.get_children())
        self.session_cache = {}
        self.tickets_by_session = data["tickets"]
        for session in data["sessions"]:
            self.session_tree.insert("", "end", iid=str(session.id), values=(
                session.name, session.place, session.start_at, session.capacity, session.enrolled,
            ))
            self.session_cache[session.id] = session
        self.ticket_tree.delete(*self.ticket_tree.get_children())

    def _pick_session(self, _event=None) -> None:
        session_id = self._iid(self.session_tree)
        if session_id is None:
            return
        session = self.session_cache[session_id]
        self.session_name.set(session.name)
        self.session_place.set(session.place)
        self.session_start.set(session.start_at)
        self.session_end.set(session.end_at)
        self.session_deadline.set(session.deadline)
        self.session_capacity.set(str(session.capacity))
        self.ticket_tree.delete(*self.ticket_tree.get_children())
        for ticket in self.tickets_by_session.get(session_id, []):
            self.ticket_tree.insert("", "end", iid=str(ticket.id), values=(
                ticket.name, ticket.charge_label(),
            ))

    def _add_session(self) -> None:
        self._run(lambda: self.system.events.add_session(
            self.actor, self.event_id, self.session_name.get(), self.session_place.get(),
            self.session_start.get(), self.session_end.get(),
            self.session_deadline.get(), self.session_capacity.get(),
        ))

    def _save_session(self) -> None:
        session_id = self._iid(self.session_tree)
        if session_id is None:
            return
        self._run(lambda: self.system.events.update_session(
            self.actor, session_id, self.session_name.get(), self.session_place.get(),
            self.session_start.get(), self.session_end.get(),
            self.session_deadline.get(), self.session_capacity.get(),
        ))

    def _delete_session(self) -> None:
        session_id = self._iid(self.session_tree)
        if session_id is None:
            return
        self._run(lambda: self.system.events.delete_session(self.actor, session_id))

    def _add_ticket(self) -> None:
        session_id = self._iid(self.session_tree)
        if session_id is None:
            messagebox.showinfo("提示", "请先选择场次", parent=self.win)
            return
        try:
            price = float(self.ticket_price.get())
        except ValueError:
            messagebox.showwarning("提示", "价格必须是数字", parent=self.win)
            return
        self._run(lambda: self.system.events.add_ticket(
            self.actor, session_id, self.ticket_name.get(), price
        ))

    def _build_people(self) -> None:
        toolbar = ttk.Frame(self.people)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="通过", command=lambda: self._review_reg(True)).pack(side="left")
        ttk.Button(
            toolbar, text="拒绝", command=lambda: self._review_reg(False)
        ).pack(side="left", padx=6)
        ttk.Button(
            toolbar, text="手动递补最早候补", command=self._promote
        ).pack(side="left")
        ttk.Button(toolbar, text="标记已支付", command=self._pay).pack(side="left", padx=6)
        grant = ttk.Frame(self.people)
        grant.pack(fill="x", pady=4)
        self.grant_user = tk.StringVar()
        ttk.Label(grant, text="授权用户编号").pack(side="left")
        ttk.Entry(grant, textvariable=self.grant_user, width=8).pack(side="left", padx=4)
        ttk.Button(grant, text="授予检票权", command=self._grant).pack(side="left")
        self.people_tree = self._tree(
            self.people,
            ("user", "phone", "code", "ticket", "status", "pay"),
            (("user", "用户", 90), ("phone", "手机", 110), ("code", "报名号", 110),
             ("ticket", "票种", 90), ("status", "状态", 80), ("pay", "支付", 80)),
        )

    def _fill_people(self) -> None:
        rows = self.system.stats.roster(self.actor, self.event_id)
        self.people_tree.delete(*self.people_tree.get_children())
        for row in rows:
            self.people_tree.insert("", "end", iid=str(row["id"]), values=(
                row["username"], row["phone"], row["code"], row["ticket"],
                row["status"], row["payment"] or "—",
            ))

    def _review_reg(self, accept: bool) -> None:
        reg_id = self._iid(self.people_tree)
        if reg_id is None:
            return
        reason = ""
        if not accept:
            reason = simpledialog.askstring("拒绝原因", "请填写原因", parent=self.win) or ""
        self._run(lambda: self.system.regs.review(self.actor, reg_id, accept, reason))

    def _promote(self) -> None:
        reg_id = self._iid(self.people_tree)
        if reg_id is None:
            return
        self._run(lambda: self.system.regs.promote_manual(self.actor, reg_id))

    def _pay(self) -> None:
        reg_id = self._iid(self.people_tree)
        if reg_id is None:
            return
        if not messagebox.askyesno("标记支付", "确认标记为已支付？", parent=self.win):
            return
        self._run(lambda: self.system.regs.mark_paid(self.actor, reg_id, True))

    def _grant(self) -> None:
        if not self.grant_user.get().strip().isdigit():
            messagebox.showwarning("提示", "请填写用户编号", parent=self.win)
            return
        self._run(lambda: self.system.users.grant_checker(
            self.actor, self.event_id, int(self.grant_user.get())
        ))

    def _build_change(self) -> None:
        self.change_type = tk.StringVar(value="场次")
        self.change_target = tk.StringVar()
        self.change_field = tk.StringVar(value="容量")
        self.change_value = tk.StringVar()
        self.change_note = tk.StringVar()
        form = ttk.Frame(self.change)
        form.pack(fill="x")
        ttk.Combobox(
            form, textvariable=self.change_type, values=("场次", "票种"), width=8, state="readonly"
        ).pack(side="left")
        ttk.Entry(form, textvariable=self.change_target, width=8).pack(side="left", padx=4)
        ttk.Combobox(
            form, textvariable=self.change_field, width=14,
            values=("开始时间", "结束时间", "报名截止时间", "容量", "价格"),
        ).pack(side="left")
        ttk.Entry(form, textvariable=self.change_value, width=20).pack(side="left", padx=4)
        ttk.Button(form, text="提交变更申请", command=self._request_change).pack(side="left")
        ttk.Label(self.change, text="对象编号是场次或票种的编号。审核通过前，对外仍是原值。").pack(anchor="w", pady=4)
        ttk.Entry(self.change, textvariable=self.change_note, width=60).pack(anchor="w")
        self.change_list = tk.Text(self.change, height=16, font=FONT)
        self.change_list.pack(fill="both", expand=True, pady=6)
        self._show_existing_changes()

    def _request_change(self) -> None:
        if not self.change_target.get().strip().isdigit():
            messagebox.showwarning("提示", "请填写对象编号", parent=self.win)
            return
        spec = (
            self.change_type.get(), int(self.change_target.get()),
            self.change_field.get(), self.change_value.get(),
        )
        self._run(lambda: self.system.events.request_change(
            self.actor, self.event_id, [spec], self.change_note.get()
        ))

    def _show_existing_changes(self) -> None:
        lines = []
        for request in self.system.events.changes_of(self.actor, self.event_id):
            lines.append(f"申请 {request.id}　{request.status.value}　{request.note}")
            for item in self.system.events.change_items(self.actor, request.id):
                lines.append(
                    f"  {item.target_type}{item.target_id} {item.field} "
                    f"{item.old_value} → {item.new_value}"
                )
        self.change_list.delete("1.0", "end")
        self.change_list.insert("1.0", "\n".join(lines) or "还没有变更申请")

    def _build_report(self) -> None:
        ttk.Button(self.report, text="导出名单", command=self._export).pack(anchor="w")
        self.report_text = tk.Text(self.report, height=18, font=FONT)
        self.report_text.pack(fill="both", expand=True, pady=6)

    def _export(self) -> None:
        if not messagebox.askyesno("导出", "确认导出报名名单？此操作会记入日志。", parent=self.win):
            return
        path = filedialog.asksaveasfilename(
            parent=self.win, defaultextension=".csv",
            filetypes=[("CSV", "*.csv")], initialfile=f"event-{self.event_id}.csv",
        )
        if not path:
            return
        try:
            text = self.system.stats.export_csv(self.actor, self.event_id, True)
        except AppError as exc:
            messagebox.showwarning("提示", str(exc), parent=self.win)
            return
        Path(path).write_text(text, encoding="utf-8-sig")
        messagebox.showinfo("已导出", path, parent=self.win)

    def _run(self, action) -> None:
        try:
            action()
        except AppError as exc:
            messagebox.showwarning("提示", str(exc), parent=self.win)
            return
        self.reload()
        if hasattr(self, "change_list"):
            self._show_existing_changes()

    def _tree(self, parent, columns, headings) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=4)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=6)
        for key, text, width in headings:
            tree.heading(key, text=text)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True)
        return tree

    def _iid(self, tree) -> int | None:
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择一行", parent=self.win)
            return None
        return int(selected[0])
