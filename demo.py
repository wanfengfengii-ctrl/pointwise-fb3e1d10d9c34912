import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.catalog import ArtifactKind, initialize_store
from archive.database import open_database
from archive.lookup import read
from calibration.admission import calibrate
from evidence.batches import Batch
from evidence.revisions import record
from handoff.bundle import export
from handoff.offline import open_bundle
from review.reports import assess


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run_shift(path, source):
    batch = Batch(source['batch_id'], source['unit'], source['coordinates'])
    claims, channels = source['claims'], source['channels']
    with closing(open_database(path)) as db:
        initialize_store(db)
        old_ref = record(db, batch, source['evidence_id'], source['old_revision'], source['old_observations'])
        old_id = calibrate(db, batch.batch_id, [old_ref])
        old_reports = [assess(db, old_id, channels, claim) for claim in claims]
        saved = [read(db, ArtifactKind.REPORT, report.report_id) for report in old_reports]
        check(all(report.parent_id == old_id for report in saved), 'incorrect old report parent')
        package = export(db, saved[0].artifact_id)
        new_ref = record(db, batch, source['evidence_id'], source['corrected_revision'],
                         source['corrected_observations'])
    with closing(open_database(path)) as db:
        initialize_store(db)
        new_id = calibrate(db, batch.batch_id, [new_ref])
        new_report = assess(db, new_id, channels, claims[0])
        new_saved = read(db, ArtifactKind.REPORT, new_report.report_id)
        check(new_saved.parent_id == new_id, 'incorrect corrected report parent')
        check(read(db, ArtifactKind.REPORT, saved[0].artifact_id) == saved[0], 'old report changed')
        check(export(db, saved[0].artifact_id) == package, 'old package changed after correction')
    offline = open_bundle(package)
    check(offline.report == saved[0], 'offline report differs from saved report')
    check(offline.calibration_id == old_id, 'offline parent differs from original calibration')
    check(offline.evidence_refs == (old_ref,), 'offline evidence differs from original selection')
    return {
        'old_marginals': [item['reachable'] for item in saved[0].data['channels']],
        'old_joint': [report.data['jointly_reachable'] for report in saved],
        'new_joint': new_saved.data['jointly_reachable'],
        'offline_joint': offline.report.data['jointly_reachable'],
        'revision': offline.evidence_refs[0].revision,
    }


def main():
    directory = Path(__file__).resolve().parent / 'examples'
    source = json.loads((directory / 'shift.json').read_text(encoding='utf-8'))
    expected = json.loads((directory / 'expected.json').read_text(encoding='utf-8'))
    with TemporaryDirectory() as temporary:
        actual = run_shift(Path(temporary) / 'shift.sqlite3', source)
    check(actual == expected, f'shift outcome differs from hand calculation: {actual!r}')
    print(json.dumps(actual, ensure_ascii=False, sort_keys=True))
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'N8', 'input': source,
        'expected': {key: expected[key] for key in ('old_marginals', 'old_joint', 'new_joint')},
        'actual': {key: actual[key] for key in ('old_marginals', 'old_joint', 'new_joint')},
        'downstream_expected': {key: expected[key] for key in ('offline_joint', 'revision')},
        'downstream_actual': {key: actual[key] for key in ('offline_joint', 'revision')},
        'code_paths': ['evidence/revisions.py', 'calibration/admission.py', 'review/reports.py',
                       'handoff/bundle.py', 'handoff/offline.py'],
        'oracle': 'x and y range over all integers individually. Their sum must be even under revision 1. '
                  'Modulus 1 in revision 2 permits all sums. The exported report uses revision 1.',
    }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
