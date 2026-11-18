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
from examples.offline_review_cases import ARRIVAL_ORDER, EXPRESSIONS, seed_calibration
from handoff.bundle import export
from handoff.offline import make_submission, make_withdrawal, open_bundle, receive
from review.reports import assess, create_review, finalize


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


def feed(db, request, order):
    outcomes = []
    for kind, side, version, claim in order:
        if kind == 'submit':
            message = make_submission(request, side, version, claim)
        else:
            message = make_withdrawal(request, side, version)
        outcomes.append(receive(db, message))
    return outcomes


def run_offline_review(path):
    with closing(open_database(path)) as db:
        initialize_store(db)
        calibration_id = seed_calibration(db)
        request = create_review(db, calibration_id, EXPRESSIONS)

        # Out-of-order delivery: left v2 arrives before left v1.
        arrivals = feed(db, request, ARRIVAL_ORDER)
        check([item['eligible'] for item in arrivals] == [True, True, True],
              'out-of-order originals must each be eligible')
        receipt = finalize(db, request['request_id'], 2, 1)
        report = read(db, ArtifactKind.REPORT, receipt['report_id'])
        check(report.parent_id == calibration_id, 'offline report parent must be the fixed calibration')
        check(report.data['jointly_reachable'] is True, 'pair (2, 1) with claims (1, 1) must pass mod 2')

        # A later withdrawal must not replace or invalidate the chosen version pair.
        withdrawal = receive(db, make_withdrawal(request, 'left', 2))
        check(withdrawal['eligible'] is False, 'withdrawn key loses eligibility')
        check(finalize(db, request['request_id'], 2, 1) == receipt,
              're-finalizing the same pair must return the original receipt')
        check(read(db, ArtifactKind.REPORT, receipt['report_id']) == report,
              'the original conclusion stays readable after withdrawal')

        # A withdrawal can arrive before the original; the late original stays unusable,
        # and a conflicting value is refused while the first value remains registered.
        early = receive(db, make_withdrawal(request, 'right', 3))
        late = receive(db, make_submission(request, 'right', 3, 2))
        check(early['eligible'] is False and late['eligible'] is False,
              'a late original behind a prior withdrawal stays ineligible')
        conflict = None
        try:
            receive(db, make_submission(request, 'right', 3, 8))
        except ValueError:
            conflict = 'refused'
        check(conflict == 'refused', 'conflicting re-submission must be rejected wholesale')

        # The other pair (1, 1) with claims (0, 1) fails mod 2 and finalizes independently.
        other = finalize(db, request['request_id'], 1, 1)
        other_report = read(db, ArtifactKind.REPORT, other['report_id'])
        check(other_report.data['jointly_reachable'] is False, 'pair (1, 1) with claims (0, 1) must fail')
        check(other['report_id'] != receipt['report_id'], 'distinct pairs publish distinct reports')

        # Correct the calibration to modulus 1 in a new revision; old conclusions stay fixed.
        corrected_id = seed_calibration(db, modulus=1, revision='2')
        corrected_request = create_review(db, corrected_id, EXPRESSIONS)

    with closing(open_database(path)) as db:
        initialize_store(db)
        # Reopen: the old request, receipt and report remain readable with their adopted versions.
        check(finalize(db, request['request_id'], 2, 1) == receipt,
              'reopen must still return the original receipt for the finalized pair')
        reopened = read(db, ArtifactKind.REPORT, receipt['report_id'])
        check(reopened == report and reopened.data['jointly_reachable'] is True,
              'reopen must preserve the original report and conclusion')
        # A new pair on the corrected modulus-1 calibration can now finalize.
        receive(db, make_submission(corrected_request, 'left', 1, 0))
        receive(db, make_submission(corrected_request, 'right', 1, 1))
        corrected_receipt = finalize(db, corrected_request['request_id'], 1, 1)
        corrected_report = read(db, ArtifactKind.REPORT, corrected_receipt['report_id'])
        check(corrected_report.data['jointly_reachable'] is True,
              'the modulus-1 correction must admit (0, 1)')
        check(corrected_report.parent_id == corrected_id, 'new report parent is the correction')

    return {
        'out_of_order_pair': {'versions': [2, 1], 'report_id': receipt['report_id'],
                              'jointly_reachable': True},
        'second_pair': {'versions': [1, 1], 'report_id': other['report_id'],
                        'jointly_reachable': False},
        'receipt_stable_after_withdrawal_and_reopen': True,
        'late_original_conflict': conflict,
        'corrected_pair': {'report_id': corrected_receipt['report_id'],
                           'jointly_reachable': True},
    }


def main():
    directory = Path(__file__).resolve().parent / 'examples'
    source = json.loads((directory / 'shift.json').read_text(encoding='utf-8'))
    expected = json.loads((directory / 'expected.json').read_text(encoding='utf-8'))
    with TemporaryDirectory() as temporary:
        actual = run_shift(Path(temporary) / 'shift.sqlite3', source)
        offline = run_offline_review(Path(temporary) / 'offline.sqlite3')
    check(actual == expected, f'shift outcome differs from hand calculation: {actual!r}')
    print(json.dumps(actual, ensure_ascii=False, sort_keys=True))
    print(json.dumps({'offline_review': offline}, ensure_ascii=False, sort_keys=True))
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
