# 活动票务与报名系统

对应实验二的领域模型：参与者报名，组织者管活动和审核，检票人员核销，管理员审核活动。

## 运行

在 `code` 目录双击 `活动汇.vbs`，或双击旁边的 `活动汇` 快捷方式。也可以在这个目录执行 `python main.py`。

会弹出活动汇自己的窗口。只需要已安装并加入 PATH 的 Python 3.11。没有额外窗口组件时，会用系统自带的 Edge 打开一个没有地址栏的窗口。若要窗口标题和图标都是「活动汇」，先在 `code` 目录执行一次：

```text
python -m pip install -r requirements.txt
```

规则自检：

```text
python selfcheck.py
```

演示账号的密码都是 `123456`。

| 用户名 | 角色 |
| --- | --- |
| admin | 平台管理员 |
| organizer | 组织者 |
| linxiao、zhou、chen | 参与者 |
| checker | 检票人员，已授权核销「校园歌手大赛」 |

数据库在 `code/data/app.db`，第一次启动自动生成。
