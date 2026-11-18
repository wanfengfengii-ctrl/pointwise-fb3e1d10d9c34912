# 编码器整刻度标定与交班台账

产线设备厂的技术员登记人工复测证据，标定员选择确切修订，质量员凭固定标定号申报两条通道，接班人员在离线工作站打开交班包。新修订可以改变下一班的标定，原报告和原包保留自己的来源和结论。

## 运行

使用 Python 3.11 标准库，在项目根目录运行。回归与演示的工作库位于各自的临时目录。

```sh
python3 -B -S -m unittest discover -s tests -v
python3 -B -S -m demo
python3 -B -S -m tests.scenario_check
```

`examples/shift.json` 保存班次输入，`examples/expected.json` 保存手算对照。偶数和标定下，x、y 各自可取任意整数，和为奇数的 (0, 1) 无法同时达到，(1, 1) 可以。模 1 更正允许所有整数对。演示在真实 SQLite 库中发布和读取报告，重开库后核对新旧结论，并关闭库后开包。

## 公开接口

```python
from contextlib import closing

from archive.catalog import ArtifactKind, initialize_store
from archive.database import open_database
from archive.lookup import read
from calibration.admission import calibrate
from evidence.batches import Batch
from evidence.revisions import record
from handoff.bundle import export
from handoff.offline import open_bundle
from review.reports import assess

with closing(open_database('shift.sqlite3')) as db:
    initialize_store(db)
    ref = record(db, Batch('line-a', 'tick', ('x', 'y')), 'bench', '1', [
        {'coefficients': {'x': 1, 'y': 1}, 'rhs': 0, 'modulus': 2},
    ])
    calibration_id = calibrate(db, 'line-a', [ref])
    report = assess(db, calibration_id, [{'x': 1}, {'y': 1}], [0, 1])
    saved = read(db, ArtifactKind.REPORT, report.report_id)
    package = export(db, report.report_id)
assert open_bundle(package).report == saved
```

批次名、单位、坐标名、证据号和修订号是非空文本。坐标顺序属于批次口径。约束中的 `coefficients` 和 `rhs` 必填。省略 `modulus` 表示等式，给出正整数表示同余。整数输入排除布尔、浮点和字符串。未列出的坐标系数为零，`{}` 是合法的零表达式。约束、修订选择、通道与申报使用列表或元组。一次标定按所选修订的顺序展开，至多 12 条约束。已登记批次可显式选择空约束。重复选入一个引用按输入次数展开；交班包为每个不同的引用保存一份证据。

`record` 返回 `EvidenceRef`，`fetch_revision` 按精确引用读取。系数映射的键顺序和零项经过规范化，同内容重放沿用旧引用。`BatchConflict` 和 `RevisionConflict` 表示对已登记口径或同一修订键提交的冲突。更正使用新修订号。缺批次或修订通过 `BatchNotFound` 或 `RevisionNotFound` 报告，输入格式错误通过 `ValueError` 报告。

`calibrate` 返回标定号。`InconsistentEvidence` 表示所选证据没有共同整数解。`calibration.snapshot.decode_calibration(saved.data)` 可读出固定坐标与整数关系，`saved` 为用 `ArtifactKind.CALIBRATION` 读取的标定成果。方向按向量保存，代表点加上各方向任意整数倍构成全部可行偏移。

`assess` 返回含 `report_id`、`reachable` 和 `jointly_reachable` 的 `Assessment`。范围保持输入位置，并编码为整数单值或 `{'residue': r, 'step': p}`，其中 `p > 0` 且 `0 <= r < p`。联合为假的正常报告同样保存。`read` 区分 `ArtifactNotFound` 和 `ArtifactTypeMismatch`，返回带精确身份、父号及原载荷字节的 `ArtifactEnvelope`。`.data` 解析已存载荷。SQLite 写错误保留原异常，提交前失败回滚整个发布。

`export` 按报告号返回可直接保存的包字节。父链缺件会拒绝导出。`open_bundle` 仅消费包字节，返回原报告、标定号和精确证据引用。坏格式、缺件、摘要或父链错配统一报 `InvalidBundle`。包清单核对内容完整性及成员一致性。
