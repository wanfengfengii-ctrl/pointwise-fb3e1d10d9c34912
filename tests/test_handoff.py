from dataclasses import replace

from archive.catalog import ArtifactKind
from archive.lookup import ArtifactNotFound, read
from archive.payloads import decode_artifact, encode_artifact, encode_payload
from calibration.admission import calibrate
from calibration.snapshot import decode_calibration
from evidence.revisions import fetch_revision
from handoff.bundle import export
from handoff.manifest import build_manifest, check_manifest
from handoff.offline import InvalidBundle, open_bundle
from handoff.serialization import BundleDocument, decode_bundle, encode_bundle
from review.reports import assess
from tests.fixtures import BATCH, XY, StoreTestCase, analysis_disabled


class HandoffTests(StoreTestCase):
    def old_report(self):
        ref, calibration_id = self.parity()
        report = assess(self.db, calibration_id, XY, [0, 1])
        return ref, calibration_id, report.report_id

    def test_offline_review(self):
        ref, calibration_id, report_id = self.old_report()
        saved = read(self.db, ArtifactKind.REPORT, report_id)
        package = export(self.db, report_id)
        self.db.close()
        offline = open_bundle(package)
        self.assertEqual(offline.report, saved)
        self.assertEqual(offline.calibration_id, calibration_id)
        self.assertEqual(offline.evidence_refs, (ref,))
        self.assertIs(offline.report.data['jointly_reachable'], False)

    def test_revision_isolation(self):
        old_ref, old_calibration, report_id = self.old_report()
        old_package = export(self.db, report_id)
        corrected, _ = self.parity(modulus=1, revision='2')
        self.reopen()
        new_calibration = calibrate(self.db, BATCH.batch_id, [corrected])
        self.assertIs(assess(self.db, old_calibration, XY, [0, 1]).jointly_reachable, False)
        self.assertIs(assess(self.db, new_calibration, XY, [0, 1]).jointly_reachable, True)
        with analysis_disabled():
            self.assertIs(read(self.db, ArtifactKind.REPORT, report_id).data['jointly_reachable'], False)
            self.assertEqual(export(self.db, report_id), old_package)
        self.db.close()
        self.assertEqual(open_bundle(old_package).evidence_refs, (old_ref,))

    def test_exact_revision_selection(self):
        old_ref, _, _ = self.old_report()
        new_ref, _ = self.parity(modulus=1, revision='2')
        self.reopen()
        for ref, modulus, expected in ((old_ref, 2, False), (new_ref, 1, True)):
            self.assertEqual(fetch_revision(self.db, ref).observations[0].modulus, modulus)
            calibration_id = calibrate(self.db, BATCH.batch_id, [ref])
            fixed = decode_calibration(read(self.db, ArtifactKind.CALIBRATION, calibration_id).data)
            self.assertEqual(fixed.evidence_refs, (ref,))
            self.assertIs(assess(self.db, calibration_id, XY, [0, 1]).jointly_reachable, expected)

    def test_no_recompute(self):
        old_ref, old_calibration, report_id = self.old_report()
        original = read(self.db, ArtifactKind.REPORT, report_id)
        self.parity(modulus=1, revision='2')
        self.reopen()
        with self.assertRaisesRegex(RuntimeError, 'analysis entry is disabled'), analysis_disabled():
            assess(self.db, old_calibration, XY, [0, 1])
        with analysis_disabled():
            self.assertEqual(read(self.db, ArtifactKind.REPORT, report_id), original)
            package = export(self.db, report_id)
        self.db.close()
        with analysis_disabled():
            offline = open_bundle(package)
        self.assertEqual(offline.report, original)
        self.assertEqual(offline.calibration_id, old_calibration)
        self.assertEqual(offline.evidence_refs, (old_ref,))
        self.assertIs(offline.report.data['jointly_reachable'], False)

    def test_content_digest(self):
        _, _, report_id = self.old_report()
        package = export(self.db, report_id)
        self.db.close()
        self.assertEqual(open_bundle(package).report.artifact_id, report_id)
        doc = decode_bundle(package)
        original = doc.members['report']
        envelope = decode_artifact(original)
        body = envelope.data
        body['channels'][0]['claimed'] = 7
        replacement = encode_artifact(replace(envelope, payload=encode_payload(body)))
        self.assertEqual(len(replacement), len(original))
        self.assertNotEqual(replacement, original)
        members = {**doc.members, 'report': replacement}
        with self.assertRaisesRegex(InvalidBundle, 'digest'):
            open_bundle(encode_bundle(BundleDocument(doc.manifest, members)))

    def test_missing_member(self):
        _, _, report_id = self.old_report()
        doc = decode_bundle(export(self.db, report_id))
        self.db.close()
        members = {name: data for name, data in doc.members.items() if name != 'evidence/1'}
        manifest = build_manifest(members)
        check_manifest(manifest, members)
        with self.assertRaisesRegex(InvalidBundle, 'evidence members'):
            open_bundle(encode_bundle(BundleDocument(manifest, members)))

    def test_mismatched_parent(self):
        _, old_calibration, old_report = self.old_report()
        _, new_calibration = self.parity(modulus=1, revision='2')
        new_report = assess(self.db, new_calibration, XY, [0, 1]).report_id
        first = decode_bundle(export(self.db, old_report))
        second = decode_bundle(export(self.db, new_report))
        self.assertNotEqual(old_calibration, new_calibration)
        self.db.close()
        members = {**second.members, 'report': first.members['report']}
        manifest = build_manifest(members)
        check_manifest(manifest, members)
        with self.assertRaisesRegex(InvalidBundle, 'report parent'):
            open_bundle(encode_bundle(BundleDocument(manifest, members)))

    def test_duplicate_selection_and_export_errors(self):
        ref, _, _ = self.old_report()
        calibration_id = calibrate(self.db, BATCH.batch_id, [ref, ref])
        report = assess(self.db, calibration_id, XY, [0, 1])
        package = export(self.db, report.report_id)
        self.assertEqual(open_bundle(package).evidence_refs, (ref, ref))
        self.assertEqual(set(decode_bundle(package).members), {'report', 'calibration', 'evidence/1'})
        with self.assertRaises(ArtifactNotFound):
            export(self.db, 'missing-report')
        with self.assertRaises(InvalidBundle):
            open_bundle(b'{"version":1,"version":1}')
