import json
import sqlite3

from archive.catalog import ArtifactKind, list_artifacts
from archive.lookup import ArtifactNotFound, read
from examples.offline_review_cases import (
    ARRIVAL_ORDER, EXPRESSIONS, PAIR_CASES, WITHDRAWAL_ORDER, seed_calibration,
)
from handoff.bundle import export
from handoff.offline import (
    make_submission, make_withdrawal, open_bundle, receive,
)
from review.reports import assess, create_review, finalize
from tests.fixtures import FailBeforeCommit, StoreTestCase


class OfflineReviewTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.calibration_id = seed_calibration(self.db)
        self.request = create_review(self.db, self.calibration_id, EXPRESSIONS)
        self.request_id = self.request['request_id']

    def submit(self, side, version, claim):
        return receive(self.db, make_submission(self.request, side, version, claim))

    def withdraw(self, side, version):
        return receive(self.db, make_withdrawal(self.request, side, version))

    def feed(self, order):
        results = []
        for kind, side, version, claim in order:
            if kind == 'submit':
                results.append(self.submit(side, version, claim))
            else:
                results.append(self.withdraw(side, version))
        return results

    def test_request_fixes_calibration_and_expressions(self):
        self.assertEqual(self.request, {
            'request_id': self.request_id,
            'calibration_id': self.calibration_id,
            'expressions': [{'x': 1}, {'y': 1}],
        })
        # Returned expressions are ordered left/right and zero coefficients are dropped.
        sparse = create_review(self.db, self.calibration_id, ({'x': 1, 'y': 0}, {}))
        self.assertEqual(sparse['expressions'], [{'x': 1}, {}])
        # The registered request copies its input: mutating the return value changes nothing.
        self.request['expressions'][0]['z'] = 9
        again = create_review(self.db, self.calibration_id, EXPRESSIONS)
        self.assertEqual(again['expressions'], [{'x': 1}, {'y': 1}])
        # Each creation allocates an independent request.
        self.assertNotEqual(again['request_id'], self.request_id)

    def test_invalid_request_inputs(self):
        for expressions in (EXPRESSIONS[0], [{'x': 1}], [{'x': 1}, {'z': 1}], 'nope'):
            with self.subTest(expressions=expressions), self.assertRaises(ValueError):
                create_review(self.db, self.calibration_id, expressions)
        with self.assertRaises(ArtifactNotFound):
            create_review(self.db, 'missing-calibration', EXPRESSIONS)

    def test_messages_are_utf8_json_with_public_fields(self):
        submission = json.loads(make_submission(self.request, 'left', 3, -7))
        self.assertEqual(set(submission), {'kind', 'request', 'side', 'version', 'claim'})
        self.assertEqual(submission['kind'], 'submit')
        self.assertEqual(submission['side'], 'left')
        self.assertEqual(submission['version'], 3)
        self.assertEqual(submission['claim'], -7)
        self.assertEqual(submission['request'], {
            'request_id': self.request_id,
            'calibration_id': self.calibration_id,
            'expressions': [{'x': 1}, {'y': 1}],
        })
        withdrawal = json.loads(make_withdrawal(self.request, 'right', 1))
        self.assertEqual(set(withdrawal), {'kind', 'request', 'side', 'version'})
        self.assertEqual(withdrawal['kind'], 'withdraw')
        self.assertIsInstance(make_submission(self.request, 'left', 1, 0), bytes)

    def test_message_integer_strictness(self):
        for builder in (
            lambda: make_submission(self.request, 'left', 1, True),
            lambda: make_submission(self.request, 'left', 1, 1.0),
            lambda: make_submission(self.request, 'left', 1, '1'),
            lambda: make_submission(self.request, 'left', True, 1),
            lambda: make_submission(self.request, 'left', 0, 1),
            lambda: make_withdrawal(self.request, 'left', 0),
            lambda: make_withdrawal(self.request, 'left', 2.0),
        ):
            with self.subTest(builder=builder), self.assertRaises(ValueError):
                builder()
        with self.assertRaises(ValueError):
            make_submission(self.request, 'middle', 1, 1)

    def test_arrival_order_and_eligibility(self):
        results = self.feed(ARRIVAL_ORDER)
        self.assertEqual([item['eligible'] for item in results], [True, True, True])
        for item in results:
            self.assertEqual(item['request_id'], self.request_id)

    def test_resend_same_key_same_value_is_idempotent(self):
        first = self.submit('left', 1, 4)
        second = self.submit('left', 1, 4)
        self.assertEqual(first, second)
        self.withdraw('left', 1)
        self.assertFalse(self.submit('left', 1, 4)['eligible'])

    def test_conflicting_value_rejects_and_keeps_first(self):
        self.submit('left', 1, 4)
        with self.assertRaises(ValueError):
            self.submit('left', 1, 5)
        # The rejected value leaves no trace: resending the first value still works.
        self.assertTrue(self.submit('left', 1, 4)['eligible'])

    def test_withdrawal_may_precede_original(self):
        # withdraw, late original, repeat original stay ineligible; the conflicting value is refused.
        results = self.feed(WITHDRAWAL_ORDER[:-1])
        self.assertEqual([item['eligible'] for item in results], [False, False, False])
        with self.assertRaises(ValueError):
            self.submit('left', 2, 0)
        with self.assertRaises(ValueError):
            self.finalize_or_none()
        # Other versions on the same side retain their own eligibility.
        self.assertTrue(self.submit('left', 1, 0)['eligible'])

    def finalize_or_none(self):
        return finalize(self.db, self.request_id, 2, 1)

    def test_repeated_withdrawal_and_independent_versions(self):
        self.withdraw('right', 1)
        self.withdraw('right', 1)
        self.assertFalse(self.submit('right', 1, 2)['eligible'])
        self.assertTrue(self.submit('right', 2, 2)['eligible'])

    def test_malformed_wire_messages_are_rejected(self):
        good = json.loads(make_submission(self.request, 'left', 1, 5))
        cases = {
            'extra field': {**good, 'extra': 1},
            'missing claim': {key: good[key] for key in ('kind', 'request', 'side', 'version')},
            'withdraw with claim': {**good, 'kind': 'withdraw'},
            'bad kind': {**good, 'kind': 'rotate'},
            'bool version': {**good, 'version': True},
            'float claim': {**good, 'claim': 1.5},
            'bad side': {**good, 'side': 'up'},
            'non-object': [1, 2, 3],
        }
        for label, value in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    receive(self.db, json.dumps(value).encode())
        with self.assertRaises(ValueError):
            receive(self.db, b'{"kind":"submit","kind":"submit"}')
        with self.assertRaises(ValueError):
            receive(self.db, 'not bytes')
        # A tampered request binding is rejected.
        tampered = json.loads(json.dumps(good))
        tampered['request']['calibration_id'] = 'other-calibration'
        with self.assertRaises(ValueError):
            receive(self.db, json.dumps(tampered).encode())
        tampered = json.loads(json.dumps(good))
        tampered['request']['expressions'] = [{'x': 1}, {'x': 1}]
        with self.assertRaises(ValueError):
            receive(self.db, json.dumps(tampered).encode())
        unknown = {**good, 'request': {'request_id': 'missing', 'calibration_id':
                                       self.calibration_id, 'expressions': list(EXPRESSIONS)}}
        with self.assertRaises(ValueError):
            receive(self.db, json.dumps(unknown).encode())

    def test_finalize_consumes_explicit_pair_and_publishes_report(self):
        self.feed(ARRIVAL_ORDER)
        receipt = finalize(self.db, self.request_id, 2, 1)
        self.assertEqual(receipt, {
            'request_id': self.request_id,
            'left_version': 2, 'right_version': 1,
            'report_id': receipt['report_id'],
        })
        report = read(self.db, ArtifactKind.REPORT, receipt['report_id'])
        self.assertEqual(report.parent_id, self.calibration_id)
        self.assertIs(report.data['jointly_reachable'], True)
        self.assertEqual([channel['claimed'] for channel in report.data['channels']], [1, 1])
        # The report remains exportable through the V1 handoff package.
        offline = open_bundle(export(self.db, receipt['report_id']))
        self.assertEqual(offline.report, report)
        self.assertEqual(offline.calibration_id, self.calibration_id)

    def test_pair_conclusions_match_hand_calculation(self):
        for versions, claims, expected_joint in PAIR_CASES:
            self.submit('left', versions[0], claims[0])
            self.submit('right', versions[1], claims[1])
            receipt = finalize(self.db, self.request_id, *versions)
            saved = read(self.db, ArtifactKind.REPORT, receipt['report_id'])
            self.assertIs(saved.data['jointly_reachable'], expected_joint)

    def test_finalize_requires_eligible_originals(self):
        self.feed(ARRIVAL_ORDER)
        # Missing right version.
        with self.assertRaises(ValueError):
            finalize(self.db, self.request_id, 2, 9)
        # Withdrawn left version stays unusable even though the original is registered.
        self.withdraw('left', 2)
        with self.assertRaises(ValueError):
            finalize(self.db, self.request_id, 2, 1)
        with self.assertRaises(ValueError):
            finalize(self.db, 'unknown-request', 1, 1)
        for left, right in ((0, 1), (1, -1), (True, 1), (1, 1.0)):
            with self.subTest(left=left, right=right), self.assertRaises(ValueError):
                finalize(self.db, self.request_id, left, right)

    def test_retry_returns_original_receipt_despite_later_withdrawal(self):
        self.feed(ARRIVAL_ORDER)
        receipt = finalize(self.db, self.request_id, 2, 1)
        self.withdraw('left', 2)
        self.assertEqual(finalize(self.db, self.request_id, 2, 1), receipt)
        saved = read(self.db, ArtifactKind.REPORT, receipt['report_id'])
        self.assertIs(saved.data['jointly_reachable'], True)

    def test_distinct_version_pairs_finalize_independently(self):
        self.submit('left', 2, 1)
        self.submit('left', 1, 0)
        self.submit('right', 1, 1)
        passing = finalize(self.db, self.request_id, 2, 1)
        failing = finalize(self.db, self.request_id, 1, 1)
        self.assertNotEqual(passing['report_id'], failing['report_id'])
        self.assertIs(read(self.db, ArtifactKind.REPORT,
                           failing['report_id']).data['jointly_reachable'], False)

    def test_finalize_atomicity_and_retry(self):
        self.feed(ARRIVAL_ORDER)
        observer = self.connect()
        fail = FailBeforeCommit(observer)
        with self.assertRaises(sqlite3.IntegrityError):
            finalize(self.db, self.request_id, 2, 1, before_commit=fail)
        with self.assertRaises(ArtifactNotFound):
            read(observer, ArtifactKind.REPORT, fail.artifact_id)
        # Neither report nor receipt survived, so the originals remain available to retry.
        before = list_artifacts(observer, ArtifactKind.REPORT)
        self.assertEqual(before, ())
        receipt = finalize(self.db, self.request_id, 2, 1)
        self.assertEqual(read(observer, ArtifactKind.REPORT, receipt['report_id']).parent_id,
                         self.calibration_id)

    def test_hook_failure_rolls_back_and_republishes(self):
        self.feed(ARRIVAL_ORDER)

        def boom(connection, report_id):
            raise RuntimeError('hook failure')

        with self.assertRaisesRegex(RuntimeError, 'hook failure'):
            finalize(self.db, self.request_id, 2, 1, before_commit=boom)
        receipt = finalize(self.db, self.request_id, 2, 1)
        self.assertIs(read(self.db, ArtifactKind.REPORT,
                           receipt['report_id']).data['jointly_reachable'], True)

    def test_reopen_preserves_requests_receipts_and_conclusions(self):
        self.feed(ARRIVAL_ORDER)
        receipt = finalize(self.db, self.request_id, 2, 1)
        self.reopen()
        self.assertEqual(finalize(self.db, self.request_id, 2, 1), receipt)
        saved = read(self.db, ArtifactKind.REPORT, receipt['report_id'])
        self.assertEqual(saved.parent_id, self.calibration_id)
        self.assertIs(saved.data['jointly_reachable'], True)
        # Late conflict registration still works after reopening.
        self.withdraw('left', 2)
        self.assertFalse(self.submit('left', 2, 1)['eligible'])
        with self.assertRaises(ValueError):
            self.submit('left', 2, 0)
        # The historical receipt remains authoritative.
        self.assertEqual(finalize(self.db, self.request_id, 2, 1), receipt)

    def test_correction_and_reopen_keep_old_conclusion(self):
        # Another review finalizes (1, 1) against the modulus-2 calibration.
        self.submit('left', 1, 0)
        self.submit('right', 1, 1)
        old_receipt = finalize(self.db, self.request_id, 1, 1)
        old_report = read(self.db, ArtifactKind.REPORT, old_receipt['report_id'])
        self.assertIs(old_report.data['jointly_reachable'], False)
        # Withdraw left v1, receive right v2, then correct to modulus 1.
        self.withdraw('left', 1)
        self.submit('right', 2, 1)
        corrected_id = seed_calibration(self.db, modulus=1, revision='2')
        self.reopen()
        # The old pair still returns the old receipt and the old failing report.
        self.assertEqual(finalize(self.db, self.request_id, 1, 1), old_receipt)
        self.assertEqual(read(self.db, ArtifactKind.REPORT, old_receipt['report_id']), old_report)
        # A fresh review on the corrected calibration admits the new pair.
        corrected_request = create_review(self.db, corrected_id, EXPRESSIONS)
        receive(self.db, make_submission(corrected_request, 'left', 1, 0))
        receive(self.db, make_submission(corrected_request, 'right', 2, 1))
        new_receipt = finalize(self.db, corrected_request['request_id'], 1, 2)
        self.assertIs(read(self.db, ArtifactKind.REPORT,
                           new_receipt['report_id']).data['jointly_reachable'], True)
        # The old request's new pair cannot finalize: its left v1 stays withdrawn.
        with self.assertRaises(ValueError):
            finalize(self.db, self.request_id, 1, 2)

    def test_integer_exact_round_trip(self):
        huge = 1 << 256
        result = self.submit('right', 7, huge)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['version'], 7)
        self.assertTrue(self.submit('right', 7, huge)['eligible'])
        with self.assertRaises(ValueError):
            self.submit('right', 7, -huge)

    def test_v1_assess_still_works_alongside_reviews(self):
        result = assess(self.db, self.calibration_id, EXPRESSIONS, [1, 1])
        saved = read(self.db, ArtifactKind.REPORT, result.report_id)
        self.assertIs(saved.data['jointly_reachable'], True)
        self.assertEqual(saved.parent_id, self.calibration_id)
