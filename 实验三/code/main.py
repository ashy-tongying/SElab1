# -*- coding: utf-8 -*-
"""启动活动票务与报名系统。"""

from __future__ import annotations

import sys


def main() -> int:
    """无参数时打开界面，--check 时只跑规则自检。"""
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        from selfcheck import main as check  # pylint: disable=import-outside-toplevel

        return check()
    from ticketapp.ui import run  # pylint: disable=import-outside-toplevel

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
