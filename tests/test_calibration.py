import sqlite3

from archive.catalog import ArtifactKind, initialize_store, list_artifacts
from archive.lookup import ArtifactNotFound, read
from calibration.admission import InconsistentEvidence, InvalidSelection, calibrate
from calibration.snapshot import decode_calibration
from evidence.batches import Batch, BatchConflict
from evidence.revisions import EvidenceRef, RevisionConflict, RevisionNotFound, fetch_revision, record
from review.reports import assess
from tests.fixtures import BATCH, XY, FailBeforeCommit, StoreTestCase, congruence, equation


class CalibrationTests(StoreTestCase):
    def fixed(self, calibration_id):
        return decode_calibration(read(self.db, ArtifactKind.CALIBRATION, calibration_id).data)

    def test_exact_marks(self):
        ref, calibration_id = self.exact()
        fixed = self.fixed(calibration_id)
        self.assertEqual(fixed.batch, BATCH)
        self.assertEqual(fixed.evidence_refs, (ref,))
        self.assertEqual(fixed.relation.point, (2, -1))
        self.assertEqual(fixed.relation.directions, ())
        self.assertEqual(list_artifacts(self.db, ArtifactKind.CALIBRATION), (calibration_id,))

    def test_revision_conflict(self):
        ref = self.marks([equation({'x': 2, 'y': 0}, 4)])
        self.assertEqual(self.marks([equation({'x': 2}, 4)]), ref)
        with self.assertRaises(RevisionConflict):
            self.marks([equation({'x': 2}, 6)])
        original, = fetch_revision(self.db, ref).observations
        self.assertEqual((original.coefficients, original.rhs), ((2, 0), 4))

    def test_integer_inconsistent(self):
        ref = self.marks([equation({'x': 1, 'y': 1}, 0), equation({'x': 1, 'y': -1}, 1)])
        with self.assertRaises(InconsistentEvidence):
            calibrate(self.db, BATCH.batch_id, [ref])
        self.assertEqual(list_artifacts(self.db, ArtifactKind.CALIBRATION), ())
        self.assertEqual([item.rhs for item in fetch_revision(self.db, ref).observations], [0, 1])

    def test_modular_contradiction(self):
        ref = self.marks([congruence({'x': 1}, 0, 2), congruence({'x': 1}, 1, 2)])
        with self.assertRaises(InconsistentEvidence):
            calibrate(self.db, BATCH.batch_id, [ref])
        self.assertEqual(list_artifacts(self.db, ArtifactKind.CALIBRATION), ())

    def test_missing_revision(self):
        ref, calibration_id = self.exact()
        missing = EvidenceRef(ref.batch_id, ref.evidence_id, 'missing')
        saved = read(self.db, ArtifactKind.CALIBRATION, calibration_id)
        with self.assertRaises(RevisionNotFound):
            calibrate(self.db, BATCH.batch_id, [missing])
        self.assertEqual(list_artifacts(self.db, ArtifactKind.CALIBRATION), (calibration_id,))
        self.assertEqual(read(self.db, ArtifactKind.CALIBRATION, calibration_id), saved)

    def test_mixed_marks(self):
        ref = self.marks([equation({'x': 1, 'y': 1}, 1), congruence({'x': 1}, -1, 4)])
        calibration_id = calibrate(self.db, BATCH.batch_id, [ref])
        relation = self.fixed(calibration_id).relation
        x, y = relation.point
        self.assertEqual(x + y, 1)
        self.assertEqual(x % 4, 3)
        self.assertIn(relation.directions, (((4, -4),), ((-4, 4),)))
        self.assertTrue(assess(self.db, calibration_id, XY, [-1, 2]).jointly_reachable)
        self.assertFalse(assess(self.db, calibration_id, XY, [1, 0]).jointly_reachable)

    def test_invalid_record(self):
        ref, calibration_id = self.exact()
        original = fetch_revision(self.db, ref)
        for observation in (equation({'z': 1}, 0), congruence({'x': 1}, 0, 0),
                            congruence({'x': 1}, 0, -3), {'coefficients': {}},
                            equation({'x': True}, 0), equation({}, 0.0)):
            with self.subTest(observation=observation):
                with self.assertRaises(ValueError):
                    self.marks([observation], 'bad')
                with self.assertRaises(RevisionNotFound):
                    fetch_revision(self.db, EvidenceRef(ref.batch_id, ref.evidence_id, 'bad'))
                self.assertEqual(fetch_revision(self.db, ref), original)
        for batch in (Batch(BATCH.batch_id, 'mm', BATCH.coordinates),
                      Batch(BATCH.batch_id, BATCH.unit, ('y', 'x'))):
            with self.assertRaises(BatchConflict):
                record(self.db, batch, 'bench', '2', [])
        self.assertEqual(self.fixed(calibration_id).batch, BATCH)

    def test_bootstrap_reopen(self):
        ref = self.marks([equation({'x': 1}, 11)], 'user-r7', 'user-reading')
        calibration_id = calibrate(self.db, BATCH.batch_id, [ref])
        evidence = fetch_revision(self.db, ref)
        saved = read(self.db, ArtifactKind.CALIBRATION, calibration_id)
        initialize_store(self.db)
        self.reopen()
        initialize_store(self.db)
        self.assertEqual(fetch_revision(self.db, ref), evidence)
        self.assertEqual(read(self.db, ArtifactKind.CALIBRATION, calibration_id), saved)
        self.assertEqual(self.marks([equation({'x': 1}, 11)], 'user-r7', 'user-reading'), ref)
        with self.assertRaises(RevisionConflict):
            self.marks([equation({'x': 1}, 12)], 'user-r7', 'user-reading')
        self.assertEqual(fetch_revision(self.db, ref), evidence)

    def test_selection_limit_and_batch(self):
        ref = self.marks([equation({}, 0)] * 6)
        accepted = calibrate(self.db, BATCH.batch_id, [ref, ref])
        other = record(self.db, Batch('other-line', 'tick', ('x',)), 'bench', '1', [])
        for selection in ([ref, ref, ref], [other]):
            with self.subTest(selection=selection), self.assertRaises(InvalidSelection):
                calibrate(self.db, BATCH.batch_id, selection)
        self.assertEqual(list_artifacts(self.db, ArtifactKind.CALIBRATION), (accepted,))

    def test_large_integers_and_eight_coordinates(self):
        names = tuple('abcdefgh')
        batch = Batch('line-wide', 'tick', names)
        enormous = -(1 << 19000)
        ref = record(self.db, batch, 'bench', 'large', [equation({'h': 1}, enormous)])
        calibration_id = calibrate(self.db, batch.batch_id, [ref])
        self.reopen()
        self.assertTrue(fetch_revision(self.db, ref).observations[0].rhs == enormous)
        result = assess(self.db, calibration_id, [{'h': 1}, {'a': 1}], [enormous, -7])
        self.assertTrue(result.reachable[0] == enormous)
        self.assertTrue(result.jointly_reachable)
        saved = read(self.db, ArtifactKind.REPORT, result.report_id)
        self.assertTrue(saved.data['channels'][0]['claimed'] == enormous)

    def test_calibration_publish_failure(self):
        ref = self.marks([equation({'x': 1}, -3)])
        observer = self.connect()
        fail = FailBeforeCommit(observer)
        with self.assertRaises(sqlite3.IntegrityError):
            calibrate(self.db, BATCH.batch_id, [ref], before_commit=fail)
        self.assertIsNotNone(fail.pending)
        self.assertIsNone(fail.visible)
        self.assertEqual(list_artifacts(observer, ArtifactKind.CALIBRATION), ())
        with self.assertRaises(ArtifactNotFound):
            read(observer, ArtifactKind.CALIBRATION, fail.artifact_id)
        retry = calibrate(self.db, BATCH.batch_id, [ref])
        self.assertEqual(list_artifacts(observer, ArtifactKind.CALIBRATION), (retry,))
