# -*- coding: utf-8 -*-
"""领域对象，对应类图里的类和枚举。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ticketapp.errors import AppError

_PASSWORD_SALT = b"selab3-ticket-v1"
_PASSWORD_ROUNDS = 20_000

ACTIVE_REG = ("待审核", "已通过", "候补中")
TERMINAL_REG = ("已签到", "已取消", "已失效", "已缺席")
HELD_STATUSES = ("已通过", "已签到")


class Role(Enum):
    """账号角色。"""

    PARTICIPANT = "参与者"
    ORGANIZER = "组织者"
    CHECKER = "检票人员"
    ADMIN = "平台管理员"


class EventStatus(Enum):
    """活动状态。"""

    DRAFT = "草稿"
    PENDING = "待审核"
    REJECTED = "已驳回"
    PUBLISHED = "已发布"
    OFFLINE = "已下架"
    CANCELLED = "已取消"
    ENDED = "已结束"


class ChangeStatus(Enum):
    """变更申请状态。"""

    PENDING = "待审核"
    APPROVED = "已通过"
    REJECTED = "已驳回"


class RegStatus(Enum):
    """报名记录状态。"""

    PENDING = "待审核"
    APPROVED = "已通过"
    WAITLIST = "候补中"
    CANCELLED = "已取消"
    CHECKED_IN = "已签到"
    INVALID = "已失效"
    ABSENT = "已缺席"


class PayStatus(Enum):
    """支付状态。免费票不使用该枚举。"""

    UNPAID = "待支付"
    PAID = "已支付"
    REFUND = "待退款"


class NoticeType(Enum):
    """通知类型。"""

    REVIEW = "审核结果"
    PROMOTED = "递补成功"
    CANCELLED = "活动取消"
    CHANGED = "关键信息变更"


# 状态图允许的报名转换。终态不在表中，不能再转。
_REG_FLOW = {
    RegStatus.PENDING: {
        RegStatus.APPROVED,
        RegStatus.WAITLIST,
        RegStatus.CANCELLED,
        RegStatus.INVALID,
    },
    RegStatus.WAITLIST: {
        RegStatus.APPROVED,
        RegStatus.CANCELLED,
        RegStatus.INVALID,
    },
    RegStatus.APPROVED: {
        RegStatus.CHECKED_IN,
        RegStatus.CANCELLED,
        RegStatus.ABSENT,
        RegStatus.INVALID,
    },
}


def digest_password(password: str) -> str:
    """生成密码摘要。演示系统使用固定盐，不保存明文。"""
    raw = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), _PASSWORD_SALT, _PASSWORD_ROUNDS
    )
    return raw.hex()


def mask_phone(phone: str) -> str:
    """名单和导出里的手机号脱敏。"""
    if len(phone) < 7:
        return "***"
    return f"{phone[:3]}****{phone[-4:]}"


def parse_time(text: str) -> datetime:
    """解析界面或变更申请里的时间。"""
    cleaned = text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    raise AppError("时间格式应为 YYYY-MM-DD HH:MM")


def format_time(value: datetime) -> str:
    """统一存成可按字符串比较的时间。"""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def ensure_time_order(deadline: str, start: str, end: str) -> None:
    """场次必须满足：报名截止 < 开始 < 结束。"""
    if not parse_time(deadline) < parse_time(start) < parse_time(end):
        raise AppError("须满足：报名截止时间 < 开始时间 < 结束时间")


@dataclass
class User:
    """用户。能否执行由角色和对象归属共同决定。"""

    id: int
    username: str
    phone: str
    password_digest: str
    role: Role
    enabled: bool

    def verify(self, password: str) -> bool:
        """核对密码。停用账号不能登录。"""
        if not self.enabled:
            return False
        return self.password_digest == digest_password(password)

    def can_execute(self, action: str, owner_id: int | None = None) -> bool:
        """类图中的「能否执行」。检票范围另看活动检票授权。"""
        if not self.enabled:
            return False
        if action in {"browse", "view_self"}:
            return True
        if action in {"register", "cancel_own"}:
            return self.role == Role.PARTICIPANT
        if action == "create_event":
            return self.role == Role.ORGANIZER
        if action in {"manage_event", "review_reg", "grant_checker"}:
            return self.role == Role.ORGANIZER and owner_id == self.id
        if action == "review_event":
            return self.role == Role.ADMIN and owner_id != self.id
        if action in {"offline", "manage_users", "view_all_logs"}:
            return self.role == Role.ADMIN
        if action == "cancel_event":
            if self.role == Role.ADMIN:
                return True
            return self.role == Role.ORGANIZER and owner_id == self.id
        if action in {"export", "mark_payment", "settle", "view_roster"}:
            if self.role == Role.CHECKER:
                return False
            if self.role == Role.ADMIN:
                return True
            return self.role == Role.ORGANIZER and owner_id == self.id
        return False


@dataclass
class CheckinGrant:
    """活动检票授权。没有授权就不能核销该活动。"""

    id: int
    event_id: int
    user_id: int
    granted_by: int
    granted_at: str

    def covers(self, event_id: int) -> bool:
        """是否覆盖该活动。"""
        return self.event_id == event_id


@dataclass
class Event:
    """活动。状态转换与状态图一致。"""

    id: int
    organizer_id: int
    title: str
    category: str
    city: str
    intro: str
    cover: str
    status: EventStatus
    need_review: bool
    reject_reason: str

    def submit_review(self) -> None:
        """草稿或已驳回，且调用方已确认信息完整时提交。"""
        if self.status not in (EventStatus.DRAFT, EventStatus.REJECTED):
            raise AppError("当前状态不能提交审核")
        self.status = EventStatus.PENDING
        self.reject_reason = ""

    def publish(self) -> None:
        """管理员通过后自动发布。"""
        if self.status != EventStatus.PENDING:
            raise AppError("只能审核待审核的活动")
        self.status = EventStatus.PUBLISHED
        self.reject_reason = ""

    def reject(self, reason: str) -> None:
        """驳回必须填写原因。"""
        if self.status != EventStatus.PENDING:
            raise AppError("只能驳回待审核的活动")
        if not reason.strip():
            raise AppError("驳回必须填写原因")
        self.status = EventStatus.REJECTED
        self.reject_reason = reason.strip()

    def take_offline(self) -> None:
        """下架只停止新报名，不改已有报名。"""
        if self.status != EventStatus.PUBLISHED:
            raise AppError("只能下架已发布的活动")
        self.status = EventStatus.OFFLINE

    def cancel(self) -> None:
        """已发布或已下架可以取消。重复取消会落在已取消状态上。"""
        if self.status in (EventStatus.CANCELLED, EventStatus.ENDED):
            raise AppError("活动已结束或已取消，不能重复取消")
        if self.status not in (EventStatus.PUBLISHED, EventStatus.OFFLINE):
            raise AppError("只有已发布或已下架的活动可以取消")
        self.status = EventStatus.CANCELLED

    def finish(self) -> None:
        """全部场次结束后进入已结束。"""
        if self.status != EventStatus.PUBLISHED:
            raise AppError("只有已发布的活动可以结束")
        self.status = EventStatus.ENDED


@dataclass
class Session:
    """场次。容量、已报名数、候补数都记在这里。"""

    id: int
    event_id: int
    name: str
    start_at: str
    end_at: str
    deadline: str
    place: str
    capacity: int
    enrolled: int
    waitlist: int

    def has_seat(self) -> bool:
        """仍有余量。已报名数只计已通过和已签到。"""
        return self.enrolled < self.capacity

    def occupy(self) -> None:
        """占用一个名额。调用方必须处于同一事务。"""
        if not self.has_seat():
            raise AppError("场次已满")
        self.enrolled += 1

    def release(self) -> None:
        """释放一个已通过名额。"""
        if self.enrolled <= 0:
            raise AppError("已报名数异常，不能再减少")
        self.enrolled -= 1

    def enter_waitlist(self) -> None:
        """候补数加一。"""
        self.waitlist += 1

    def leave_waitlist(self) -> None:
        """候补数减一。"""
        if self.waitlist <= 0:
            raise AppError("候补数异常，不能再减少")
        self.waitlist -= 1

    def remaining(self) -> int:
        """剩余名额，不为负。"""
        return max(self.capacity - self.enrolled, 0)


@dataclass
class TicketType:
    """票种。价格按所属场次独立。"""

    id: int
    session_id: int
    name: str
    price: float
    is_free: bool

    def set_price(self, price: float) -> None:
        """校验并写价格。0 为免费票，大于 0 为收费票。"""
        if price < 0:
            raise AppError("价格不能为负")
        self.price = round(float(price), 2)
        self.is_free = self.price == 0
        if not self.is_free and self.price <= 0:
            raise AppError("收费票价格必须大于 0")

    def charge_label(self) -> str:
        """界面上的价格文字。"""
        if self.is_free:
            return "免费"
        return f"{self.price:.2f} 元"


@dataclass
class ChangeItem:
    """一条关键信息变更。审核结束前对外仍用原值。"""

    id: int
    request_id: int
    target_type: str
    target_id: int
    field: str
    old_value: str
    new_value: str


@dataclass
class ChangeRequest:
    """变更申请。"""

    id: int
    event_id: int
    applicant_id: int
    status: ChangeStatus
    note: str
    reviewer_id: int | None
    review_comment: str
    created_at: str

    def take_effect(self, reviewer_id: int, comment: str, apply) -> None:
        """通过后先生效，再改申请状态。apply 负责写回场次和票种。"""
        if self.status != ChangeStatus.PENDING:
            raise AppError("该变更申请已处理")
        apply()
        self.status = ChangeStatus.APPROVED
        self.reviewer_id = reviewer_id
        self.review_comment = comment.strip()

    def reject(self, reviewer_id: int, comment: str) -> None:
        """驳回变更，原值继续有效。"""
        if self.status != ChangeStatus.PENDING:
            raise AppError("该变更申请已处理")
        if not comment.strip():
            raise AppError("驳回必须填写原因")
        self.status = ChangeStatus.REJECTED
        self.reviewer_id = reviewer_id
        self.review_comment = comment.strip()


@dataclass
class Registration:
    """报名记录。同一用户在同一场次只能有一条有效报名。"""

    id: int
    code: str
    user_id: int
    session_id: int
    ticket_id: int
    status: RegStatus
    reason: str
    payment: PayStatus | None
    waitlist_at: str | None
    created_at: str

    def is_active(self) -> bool:
        """待审核、已通过、候补中算有效。已取消或已失效后可以再报。"""
        return self.status.value in ACTIVE_REG

    def transition_to(self, new_status: RegStatus) -> None:
        """只允许状态图中的路径。"""
        allowed = _REG_FLOW.get(self.status, set())
        if new_status not in allowed:
            raise AppError(
                f"不能从「{self.status.value}」改为「{new_status.value}」"
            )
        self.status = new_status

    def mark_payment(self, new_status: PayStatus) -> None:
        """免费票没有支付状态，不能标记。"""
        if self.payment is None:
            raise AppError("免费票不能标记支付状态")
        if self.payment == PayStatus.REFUND:
            raise AppError("待退款记录不能再标记支付")
        if new_status != PayStatus.PAID:
            raise AppError("只能把收费票标记为已支付")
        self.payment = new_status

    def mark_refund_if_charged(self) -> None:
        """活动取消时，收费票未完结的支付状态改为待退款。"""
        if self.payment in (PayStatus.UNPAID, PayStatus.PAID):
            self.payment = PayStatus.REFUND


@dataclass
class CheckinRecord:
    """成功签到记录。一条报名最多一条。"""

    id: int
    registration_id: int
    checker_id: int
    checked_at: str


@dataclass
class Notification:
    """站内通知。本期不发短信、不做推送。"""

    id: int
    receiver_id: int
    ntype: NoticeType
    event_id: int
    session_id: int | None
    content: str
    created_at: str
    read_at: str | None

    def mark_read(self, when: str) -> None:
        """标记已读。重复标记不改第一次的时间。"""
        if self.read_at:
            return
        self.read_at = when


@dataclass
class AuditEntry:
    """操作日志。只有追加，没有修改和删除。"""

    id: int
    actor_id: int
    action: str
    target_type: str
    target_id: int
    result: str
    detail: str
    event_id: int | None
    created_at: str

    @staticmethod
    def refuse_mutation() -> None:
        """代码路径上的不可篡改约束。数据库触发器是第二道。"""
        raise AppError("日志只能追加，不能修改或删除")
