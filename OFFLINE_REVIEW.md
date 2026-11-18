# 双工位离线复核

`README.md` 介绍现有的证据登记、标定、复核及离线开包。两台工位拿到同一复核请求后可独立填报各自的一侧。在线质控员选择明确的两侧版本定稿。报告继续使用原有 `ArtifactKind.REPORT`、父标定号及载荷格式，采用的版本从定稿回执查阅。

## 请求与离线消息

在 `review.reports` 提供 `create_review(db, calibration_id, expressions)`。每次成功创建一个独立请求，返回含 `request_id`、`calibration_id`、`expressions` 的字典。标定和请求号为非空字符串。`expressions` 在输入时沿用 `assess` 的表达式校验，返回时为两个字典组成的列表，首项为左侧，次项为右侧，省去零系数。请求固定该标定和表达式，复制输入。修改返回值不改变已登记请求。标定不存在或类型错误沿用原 `read` 的错误类型。

在 `handoff.offline` 提供 `make_submission(request, side, version, claim)` 和 `make_withdrawal(request, side, version)`。两个函数离线返回 UTF-8 JSON 字节。消息对象有 `kind`、`request`、`side`、`version` 四个公共字段。`request` 为上述三个固定字段组成的对象。`kind` 为 `submit` 时另有 `claim` 字段，为 `withdraw` 时仅有公共字段。侧别为 `left` 或 `right`。`version` 为正整数，`claim` 为带符号整数，布尔、浮点及字符串均不可充作整数。整数须精确往返。消息字段次序和 JSON 空白无须一致，重复或多余字段拒绝。

在 `handoff.offline` 提供 `receive(db, message)`，接收上述字节。登记前核对请求存在，消息中的标定号和有序表达式与原请求一致。返回含 `request_id`、`side`、`version`、`eligible` 的字典，其中 `eligible` 为接纳之后的布尔资格。资格表示该键已有原件且从未撤回。按请求、侧别、版本核对原件。同键同值重送仍返回当前资格，同键异值拒绝。撤回只作用于所指的键，可以先于原件或重复送达。迟到原件的首值仍须登记供冲突核对，资格持续为假。同一侧的其余版本各自保留资格。非法字段、未知或错绑请求、同键冲突均抛出 `ValueError` 且不改账。

## 定稿与读取

在 `review.reports` 提供 `finalize(db, request_id, left_version, right_version, *, before_commit=None)`。请求号和两个版本同上。返回字典 `{'request_id': request_id, 'left_version': left_version, 'right_version': right_version, 'report_id': report_id}`。

同一请求内，左右版本对分别定稿。已有回执时返回原回执，随后撤回不影响该回执。首次定稿时两侧都必须已有原件且未撤回，缺件、撤回、未知请求或非法键抛出 `ValueError`。联合复核按请求固定的标定和表达式消费两份指定申报，真假都发布。首次定稿把报告和回执一起提交，资格裁决以该次提交边界为准。可传入与 V1 同形状的 `before_commit(db, report_id)`，在首次定稿的报告和回执均已写入、尚未提交时调用。钩子或数据库写入失败时原异常向外抛出，本次报告及回执均回滚，原申报可供重试。历史回执无需再发布。

用 `read(db, ArtifactKind.REPORT, report_id)` 查已保存的结论和标定父号。更正证据、发布新标定或关闭重开数据库后，旧请求和已定稿报告仍由原标定及版本对确定。原 `initialize_store`、`assess`、`read`、`export` 和 `open_bundle` 的公开用法、已有报告编码及 V1 交班格式继续有效。

## 样例

`examples/offline_review_cases.py` 提供按送达次序排列的 `(kind, side, version, claim)`，撤回行的最后一项为夹具中的 `None`。夹具可登记固定标定，并用现有 `assess` 核对联合结论的手算值。下面是在已初始化的数据库连接 `db` 上使用新增接口的调用示例。

```python
from archive.catalog import ArtifactKind
from archive.lookup import read
from examples.offline_review_cases import EXPRESSIONS, seed_calibration
from handoff.offline import make_submission, make_withdrawal, receive
from review.reports import create_review, finalize

calibration_id = seed_calibration(db)
request = create_review(db, calibration_id, EXPRESSIONS)
receive(db, make_submission(request, 'left', 2, 1))
receive(db, make_submission(request, 'left', 1, 0))
receive(db, make_submission(request, 'right', 1, 1))
receipt = finalize(db, request['request_id'], 2, 1)
report = read(db, ArtifactKind.REPORT, receipt['report_id'])
assert report.parent_id == calibration_id
assert report.data['jointly_reachable'] is True
receive(db, make_withdrawal(request, 'left', 2))
assert finalize(db, request['request_id'], 2, 1) == receipt
```

模 2 时，版本对 `(2, 1)` 的申报为 `(1, 1)`，和为偶数，故通过。版本对 `(1, 1)` 的申报为 `(0, 1)`，和为奇数，故不通过。先撤回左第 2 版再依次收到 1、1、0 时，前两份原件返回资格为假，最后一份报冲突。另一次复核若已用 `(1, 1)` 定稿，随后撤回左第 1 版、收到右第 2 版并更正为模 1，重开后旧对仍返回旧回执和不通过报告，新对 `(1, 2)` 则拒绝首次定稿。

## 运行清单

沿用根目录的 `.pointwise-runtime.json`。`version` 为 1，`kind` 为 `cli`。`setup` 是启动核验或演示前要执行的命令列表，每条为 argv。`verify` 和 `demo` 各为一条 argv。接通原回归与新增复核联动核验，检查失败须以非零状态退出。演示应展示乱序定稿、撤回及重开后的实际报告与回执。用简短说明记录接纳资格、定稿裁决与回执之间的交接约定。
