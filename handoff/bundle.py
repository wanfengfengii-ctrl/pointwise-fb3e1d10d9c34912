from archive.catalog import ArtifactKind
from archive.lookup import read
from archive.payloads import encode_artifact, encode_payload
from calibration.snapshot import decode_calibration
from evidence.batches import check_batch_compatibility
from evidence.revisions import encode_revision, fetch_revision
from handoff.manifest import build_manifest
from handoff.serialization import BundleDocument, encode_bundle, evidence_slots


def export(connection, report_id):
    report = read(connection, ArtifactKind.REPORT, report_id)
    calibration = read(connection, ArtifactKind.CALIBRATION, report.parent_id)
    fixed = decode_calibration(calibration.data)
    members = {'report': encode_artifact(report), 'calibration': encode_artifact(calibration)}
    for name, ref in evidence_slots(fixed.evidence_refs).items():
        revision = fetch_revision(connection, ref)
        check_batch_compatibility(fixed.batch, revision.batch)
        members[name] = encode_payload(encode_revision(revision))
    return encode_bundle(BundleDocument(build_manifest(members), members))
