# -*- coding: utf-8 -*-
"""可替换的时钟，便于测试截止时间和缺席结算。"""

from __future__ import annotations

from datetime import datetime


class Clock:
    """系统时间。"""

    def now(self) -> datetime:
        """当前时间，去掉微秒，保证同一秒内仍可排序。"""
        return datetime.now().replace(microsecond=0)
