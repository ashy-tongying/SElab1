# -*- coding: utf-8 -*-
"""把各业务包组装成一个系统。界面只通过这里调用。"""

from __future__ import annotations

from pathlib import Path

from ticketapp.audit import AuditService
from ticketapp.checkin import CheckinService
from ticketapp.clock import Clock
from ticketapp.database import Database
from ticketapp.events import EventService
from ticketapp.notify import NotifyService
from ticketapp.registration import RegistrationService
from ticketapp.seed import PASSWORD, prepare
from ticketapp.stats import StatsService
from ticketapp.users import UserService


def default_db_path() -> Path:
    """数据库放在 code/data，不进版本库。"""
    return Path(__file__).resolve().parent.parent / "data" / "app.db"


class System:
    """活动票务与报名系统。"""

    def __init__(self, path=None, clock=None, demo: bool = True) -> None:
        self.clock = clock or Clock()
        self.database = Database(path or default_db_path())
        self.database.init()
        self.audit = AuditService(self.database, self.clock)
        self.notify = NotifyService(self.database, self.clock)
        self.users = UserService(self.database, self.audit, self.clock)
        self.regs = RegistrationService(
            self.database, self.audit, self.notify, self.clock
        )
        self.events = EventService(
            self.database, self.audit, self.notify, self.clock, self.regs
        )
        self.checkin = CheckinService(self.database, self.audit, self.clock)
        self.stats = StatsService(self.database, self.audit)
        prepare(self, demo)
        self._settle_published()

    def _settle_published(self) -> None:
        """启动时做一次到期结算，相当于状态图里的定时任务。"""
        try:
            admin = self.users.login("admin", PASSWORD)
        except Exception:
            return
        self.regs.settle_due(admin, None)
