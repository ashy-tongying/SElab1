# -*- coding: utf-8 -*-
"""业务异常。界面只展示 AppError 的文字。"""

from __future__ import annotations


class AppError(Exception):
    """规则不允许当前操作时抛出，消息可直接给用户看。"""


class RuleBreak(Exception):
    """事务内发现必须拒绝的情况。

    调用方先回滚业务写入，再单独追加一条拒绝日志。
    这样拒绝记录不会被同一次回滚抹掉，与报名时序图一致。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
