import json
import sqlite3

from archive.catalog import ArtifactKind, list_artifacts
from archive.lookup import ArtifactNotFound, ArtifactTypeMismatch, read
from calibration.admission import calibrate
from review.projection import ResidueClass
from review.reports import assess
from tests.fixtures import BATCH, XY, FailBeforeCommit, StoreTestCase


class ReviewTests(StoreTestCase):
    def test_shared_parity(self):
        _, calibration_id = self.parity()
        impossible = assess(self.db, calibration_id, XY, [0, 1])
        possible = assess(self.db, calibration_id, XY, [1, 1])
        self.assertEqual(impossible.reachable, (ResidueClass(0, 1),) * 2)
        self.assertEqual(possible.reachable, impossible.reachable)
        self.assertIs(impossible.jointly_reachable, False)
        self.assertIs(possible.jointly_reachable, True)
        saved = [read(self.db, ArtifactKind.REPORT, result.report_id) for result in (impossible, possible)]
        self.assertEqual([artifact.parent_id for artifact in saved], [calibration_id, calibration_id])
        observed = [artifact.data['jointly_reachable'] for artifact in saved]
        self.assertEqual(observed, [False, True])
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'N4', 'input': {'constraint': 'x+y=0 mod 2', 'claims': [[0, 1], [1, 1]]},
            'expected': [False, True], 'actual': [impossible.jointly_reachable, possible.jointly_reachable],
            'downstream_expected': [False, True], 'downstream_actual': observed,
            'code_paths': ['calibration/admission.py', 'calibration/snapshot.py', 'review/joint.py',
                           'review/reports.py', 'archive/lookup.py'],
            'oracle': 'The claimed sums are 1 and 2. The first is odd, the second is even.',
        }, sort_keys=True))

    def test_zero_and_repeated(self):
        _, calibration_id = self.exact()
        repeated = assess(self.db, calibration_id, [{'x': 1}, {'x': 1}], [2, 3])
        self.assertEqual(repeated.reachable, (2, 2))
        self.assertIs(repeated.jointly_reachable, False)
        zero = assess(self.db, calibration_id, [{}, {'x': 1}], [0, 2])
        self.assertEqual(zero.reachable, (0, 2))
        self.assertIs(zero.jointly_reachable, True)
        self.assertEqual(read(self.db, ArtifactKind.REPORT, zero.report_id).data['channels'], [
            {'coefficients': {}, 'claimed': 0, 'reachable': 0},
            {'coefficients': {'x': 1}, 'claimed': 2, 'reachable': 2},
        ])

    def test_frozen_relation(self):
        _, even = self.parity()
        _, unrestricted = self.parity(modulus=1, revision='2')
        self.reopen()
        for calibration_id, expected in ((even, [False, True]), (unrestricted, [True, True])):
            for values, passes in zip(((0, 1), (1, 1)), expected, strict=True):
                with self.subTest(calibration_id=calibration_id, claims=values):
                    result = assess(self.db, calibration_id, XY, values)
                    self.assertEqual(result.reachable, (ResidueClass(0, 1),) * 2)
                    self.assertIs(result.jointly_reachable, passes)
                    saved = read(self.db, ArtifactKind.REPORT, result.report_id)
                    self.assertEqual(saved.parent_id, calibration_id)
                    self.assertIs(saved.data['jointly_reachable'], passes)

    def test_stride_normalization(self):
        _, calibration_id = self.parity(rhs=1)
        channels = ({'x': -2, 'y': -2}, {'x': 1})
        for claims, passes in (((-2, 0), True), ((0, 0), False)):
            result = assess(self.db, calibration_id, channels, claims)
            self.assertEqual(result.reachable, (ResidueClass(2, 4), ResidueClass(0, 1)))
            self.assertIs(result.jointly_reachable, passes)
            saved = read(self.db, ArtifactKind.REPORT, result.report_id)
            self.assertEqual(saved.data['channels'][0]['reachable'], {'residue': 2, 'step': 4})

    def test_ordered_stride(self):
        _, calibration_id = self.parity(rhs=1)
        result = assess(self.db, calibration_id, [{}, {'x': -2, 'y': -2}], [0, -2])
        self.assertEqual(result.reachable, (0, ResidueClass(2, 4)))
        self.assertIs(result.jointly_reachable, True)
        self.assertEqual(read(self.db, ArtifactKind.REPORT, result.report_id).data['channels'], [
            {'coefficients': {}, 'claimed': 0, 'reachable': 0},
            {'coefficients': {'x': -2, 'y': -2}, 'claimed': -2, 'reachable': {'residue': 2, 'step': 4}},
        ])

    def test_invalid_expression(self):
        _, calibration_id = self.exact()
        for channels, values in (([{}, {'z': 1}], [0, 1]), ([{}], [0, 1]), (XY, [0, True])):
            with self.subTest(channels=channels, values=values), self.assertRaises(ValueError):
                assess(self.db, calibration_id, channels, values)
        with self.assertRaises(ArtifactNotFound):
            assess(self.db, 'missing-calibration', XY, [0, 1])
        self.assertEqual(list_artifacts(self.db, ArtifactKind.REPORT), ())

    def test_explicit_empty_constraints(self):
        ref = self.marks([])
        for selection in ([ref], []):
            calibration_id = calibrate(self.db, BATCH.batch_id, selection)
            result = assess(self.db, calibration_id, XY, [-10, 13])
            self.assertEqual(result.reachable, (ResidueClass(0, 1),) * 2)
            self.assertIs(result.jointly_reachable, True)

    def test_publish_retry(self):
        _, calibration_id = self.parity()
        observer = self.connect()
        parent = read(observer, ArtifactKind.CALIBRATION, calibration_id)
        fail = FailBeforeCommit(observer)
        with self.assertRaises(sqlite3.IntegrityError):
            assess(self.db, calibration_id, XY, [1, 1], before_commit=fail)
        with self.assertRaises(ArtifactNotFound):
            read(observer, ArtifactKind.REPORT, fail.artifact_id)
        self.assertEqual(read(observer, ArtifactKind.CALIBRATION, calibration_id), parent)
        retry = assess(self.db, calibration_id, XY, [1, 1])
        saved = read(observer, ArtifactKind.REPORT, retry.report_id)
        self.assertEqual(saved.parent_id, calibration_id)
        self.assertIs(saved.data['jointly_reachable'], True)

    def test_catalog_atomicity(self):
        _, calibration_id = self.parity()
        observer = self.connect()
        earlier = assess(self.db, calibration_id, XY, [1, 1])
        parent = read(observer, ArtifactKind.CALIBRATION, calibration_id)
        original = list_artifacts(observer, ArtifactKind.REPORT)
        fail = FailBeforeCommit(observer)
        with self.assertRaises(sqlite3.IntegrityError):
            assess(self.db, calibration_id, XY, [0, 1], before_commit=fail)
        self.assertEqual(fail.pending[:3], (ArtifactKind.REPORT, fail.artifact_id, calibration_id))
        self.assertIsNone(fail.visible)
        self.assertEqual(list_artifacts(observer, ArtifactKind.REPORT), original)
        with self.assertRaises(ArtifactNotFound):
            read(observer, ArtifactKind.REPORT, fail.artifact_id)
        self.assertEqual(read(observer, ArtifactKind.CALIBRATION, calibration_id), parent)
        retry = assess(self.db, calibration_id, XY, [0, 1])
        self.assertEqual(set(list_artifacts(observer, ArtifactKind.REPORT)), {earlier.report_id, retry.report_id})
        saved = read(observer, ArtifactKind.REPORT, retry.report_id)
        self.assertEqual(saved.parent_id, calibration_id)
        self.assertIs(saved.data['jointly_reachable'], False)
        self.assertEqual(len(saved.data['channels']), 2)

    def test_read_contract(self):
        _, calibration_id = self.exact()
        report = assess(self.db, calibration_id, XY, [2, -1])
        with self.assertRaises(ArtifactNotFound):
            read(self.db, ArtifactKind.REPORT, 'missing')
        with self.assertRaises(ArtifactTypeMismatch):
            read(self.db, ArtifactKind.CALIBRATION, report.report_id)
        saved = read(self.db, ArtifactKind.REPORT, report.report_id)
        self.assertEqual(saved.parent_id, calibration_id)
        self.assertIs(saved.data['jointly_reachable'], True)
